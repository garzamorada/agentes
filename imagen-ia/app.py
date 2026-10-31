"""imagen-ia: generación de imágenes con IA en la GPU.

Modelos (IMAGEN_MODELO):
- flux2-klein (por defecto): FLUX.2 [klein] 4B de Black Forest Labs (Apache 2.0). Text encoder Qwen3-4B en 4 bits (NF4)
  para que entre en 12 GB de VRAM; transformer en bf16 (o NF4 con FLUX_TRANSFORMER=nf4). Mejor siguiendo el prompt y
  escribiendo texto que SDXL.
- sdxl-lightning: Stable Diffusion XL + SDXL-Lightning de 4 pasos (más liviano).

POST /generar  → {prompt, negativo?, ancho?, alto?, cantidad?, semilla?}  (header X-API-Key)
GET  /health

Comparte la GPU con Ollama: antes de cargar el modelo le pide a Ollama que descargue los suyos, y después de
INACTIVIDAD_S segundos sin pedidos libera la VRAM para que Ollama la vuelva a usar.
Los pesos se descargan la primera vez a HF_HOME (volumen de Docker) y quedan ahí.
"""
import asyncio
import datetime
import gc
import os
import re
import secrets
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import torch
from accelerate import init_empty_weights
from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
from diffusers import BitsAndBytesConfig as DiffusersBnb
from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel
from transformers import BitsAndBytesConfig, Qwen3ForCausalLM
from fastapi import Depends, FastAPI, Header, HTTPException
from huggingface_hub import hf_hub_download
from pydantic import BaseModel, Field
from safetensors.torch import load_file

API_KEY = os.environ.get('IMAGEN_IA_API_KEY', '')
if not API_KEY:
    raise SystemExit('Falta IMAGEN_IA_API_KEY (ver .env.default)')
DATA = Path(os.environ.get('DATA_DIR', '/data'))
PUBLIC = os.environ.get('PUBLIC_URL', 'http://localhost:8090').rstrip('/')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://ollama:11434').rstrip('/')
INACTIVIDAD = int(os.environ.get('INACTIVIDAD_S', '180'))

MODELO = os.environ.get('IMAGEN_MODELO', 'flux2-klein').strip().lower()
FLUX = 'black-forest-labs/FLUX.2-klein-4B'                 # licencia Apache 2.0
FLUX_TRANSFORMER = os.environ.get('FLUX_TRANSFORMER', 'bf16').strip().lower()   # bf16 | nf4
BASE = 'stabilityai/stable-diffusion-xl-base-1.0'          # licencia CreativeML Open RAIL++-M
LIGHTNING = ('ByteDance/SDXL-Lightning', 'sdxl_lightning_4step_unet.safetensors')
VAE = 'madebyollin/sdxl-vae-fp16-fix'                      # VAE de SDXL que no da imágenes negras en fp16
PASOS = 4
MAX_PIXELES_FLUX = int(os.environ.get('FLUX_MAX_PIXELES', str(1024 * 1024)))
NOMBRE_MODELO = (f'FLUX.2 klein 4B ({"transformer NF4" if FLUX_TRANSFORMER == "nf4" else "bf16"}, text encoder NF4)'
                 if MODELO.startswith('flux') else 'SDXL-Lightning 4 pasos')

estado = {'pipe': None, 'usado': 0.0, 'cargando': False}
lock = asyncio.Lock()


def requiere_clave(x_api_key: str = Header(default='')):
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, 'Falta o es incorrecta la clave (header X-API-Key)')


# ---------- GPU compartida con Ollama ----------
async def liberar_ollama():
    """Pide a Ollama que descargue los modelos que tiene en la GPU (keep_alive=0)."""
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            cargados = (await c.get(f'{OLLAMA_URL}/api/ps')).json().get('models', [])
            for m in cargados:
                await c.post(f'{OLLAMA_URL}/api/generate', json={'model': m['name'], 'keep_alive': 0})
        if cargados:
            await asyncio.sleep(2)
        return [m['name'] for m in cargados]
    except (httpx.HTTPError, ValueError):
        return []


def _nf4(clase):
    return clase(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_compute_dtype=torch.bfloat16)


def _cargar_flux():
    """Cada componente va directo a la GPU (sin pasar entero por la RAM del contenedor)."""
    gpu = {'': 0}
    text_encoder = Qwen3ForCausalLM.from_pretrained(FLUX, subfolder='text_encoder', dtype=torch.bfloat16,
                                                    quantization_config=_nf4(BitsAndBytesConfig), device_map=gpu)
    extra = {'quantization_config': _nf4(DiffusersBnb)} if FLUX_TRANSFORMER == 'nf4' else {}
    transformer = Flux2Transformer2DModel.from_pretrained(FLUX, subfolder='transformer', torch_dtype=torch.bfloat16,
                                                          device_map='cuda', **extra)
    pipe = Flux2KleinPipeline.from_pretrained(FLUX, transformer=transformer, text_encoder=text_encoder,
                                              torch_dtype=torch.bfloat16)
    pipe.vae.to('cuda')
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _cargar():
    return _cargar_flux() if MODELO.startswith('flux') else _cargar_sdxl()


def _cargar_sdxl():
    # UNet "vacía" (sin reservar memoria) y los pesos de Lightning (fp16) directo a la GPU:
    # crearla normal ocupaba ~10 GB de RAM en fp32 y el contenedor se quedaba sin memoria.
    with init_empty_weights():
        unet = UNet2DConditionModel.from_config(UNet2DConditionModel.load_config(BASE, subfolder='unet'))
    unet.load_state_dict(load_file(hf_hub_download(*LIGHTNING), device='cuda'), assign=True)
    unet = unet.to('cuda', torch.float16)
    vae = AutoencoderKL.from_pretrained(VAE, torch_dtype=torch.float16)
    pipe = StableDiffusionXLPipeline.from_pretrained(BASE, unet=unet, vae=vae, torch_dtype=torch.float16,
                                                     variant='fp16', use_safetensors=True).to('cuda')
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing='trailing')
    pipe.set_progress_bar_config(disable=True)
    return pipe


def _descargar():
    estado['pipe'] = None
    gc.collect()
    torch.cuda.empty_cache()


async def vigilar_inactividad():
    while True:
        await asyncio.sleep(30)
        if estado['pipe'] is not None and not lock.locked() and time.time() - estado['usado'] > INACTIVIDAD:
            async with lock:
                _descargar()


@asynccontextmanager
async def lifespan(_):
    DATA.mkdir(parents=True, exist_ok=True)
    t = asyncio.create_task(vigilar_inactividad())
    yield
    t.cancel()


app = FastAPI(title='imagen-ia', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class Pedido(BaseModel):
    prompt: str = Field(min_length=3, max_length=1500)
    negativo: str = Field(default='', max_length=600)
    ancho: int = 1024
    alto: int = 1024
    cantidad: int = Field(default=1, ge=1, le=4)
    semilla: int | None = None
    nombre: str = ''


def _medida(v: int) -> int:
    """Entre 512 y 1536 px; múltiplos de 64 (SDXL) o de 16 (FLUX)."""
    paso = 16 if MODELO.startswith('flux') else 64
    return max(512, min(1536, int(round(int(v) / paso) * paso)))


def _slug(t: str) -> str:
    t = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '_', t).strip('_')[:50] or 'imagen'


@app.get('/health')
def health():
    return {'ok': True, 'modelo': NOMBRE_MODELO, 'gpu': torch.cuda.is_available(), 'cargado': estado['pipe'] is not None,
            'vram_libre_gb': round(torch.cuda.mem_get_info()[0] / 2**30, 1) if torch.cuda.is_available() else None}


@app.post('/generar', dependencies=[Depends(requiere_clave)])
async def generar(p: Pedido):
    if not torch.cuda.is_available():
        raise HTTPException(503, 'No hay GPU disponible en el contenedor')
    ancho, alto = _medida(p.ancho), _medida(p.alto)
    if MODELO.startswith('flux') and ancho * alto > MAX_PIXELES_FLUX:
        # Más de ~1 megapíxel no entra en los 12 GB junto con el modelo: se achica manteniendo la proporción
        f = (MAX_PIXELES_FLUX / (ancho * alto)) ** 0.5
        ancho, alto = max(512, int(ancho * f) // 16 * 16), max(512, int(alto * f) // 16 * 16)
    t0 = time.time()
    async with lock:
        liberados = []
        if estado['pipe'] is None:
            liberados = await liberar_ollama()
            try:
                estado['pipe'] = await asyncio.to_thread(_cargar)
            except torch.cuda.OutOfMemoryError:
                _descargar()
                liberados += await liberar_ollama()   # Ollama pudo haber vuelto a cargar algo: se reintenta una vez
                estado['pipe'] = await asyncio.to_thread(_cargar)
        carga = round(time.time() - t0, 1)
        semilla = p.semilla if p.semilla is not None else secrets.randbelow(2**31)
        gen = torch.Generator('cuda').manual_seed(semilla)

        def correr():
            if MODELO.startswith('flux'):
                # FLUX.2 klein destilado: 4 pasos, guidance 1.0; no usa prompt negativo.
                # De a una: en 12 GB, generar varias juntas desborda la VRAM y el driver usa RAM compartida (4x más lento).
                return [estado['pipe'](prompt=p.prompt, width=ancho, height=alto, num_inference_steps=4, guidance_scale=1.0,
                                       generator=torch.Generator('cuda').manual_seed(semilla + i)).images[0]
                        for i in range(p.cantidad)]
            return estado['pipe'](prompt=p.prompt, negative_prompt=p.negativo or None, width=ancho, height=alto,
                                  num_inference_steps=PASOS, guidance_scale=0.0, num_images_per_prompt=p.cantidad,
                                  generator=gen).images
        try:
            imagenes = await asyncio.to_thread(correr)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            raise HTTPException(507, 'Sin memoria de GPU: probá con menos imágenes o un tamaño menor.')
        estado['usado'] = time.time()

    carpeta = DATA / f'ia-{datetime.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
    carpeta.mkdir(parents=True, exist_ok=True)
    base = _slug(p.nombre or p.prompt)
    archivos = []
    for i, img in enumerate(imagenes, 1):
        nombre = f'{base}{"_" + str(i) if len(imagenes) > 1 else ""}.png'
        img.save(carpeta / nombre)
        archivos.append({'nombre': nombre, 'url': f'{PUBLIC}/files/{carpeta.name}/{nombre}'})
    return {'archivos': archivos, 'ancho': ancho, 'alto': alto, 'semilla': semilla, 'modelo': NOMBRE_MODELO,
            'segundos': round(time.time() - t0, 1), 'segundos_carga': carga, 'ollama_liberado': liberados}
