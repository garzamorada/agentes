---
name: vision-fundamentos
description: Diseñar y evaluar soluciones de visión por computadora: tarea, datos, modelo, métricas, despliegue en GPU o edge y privacidad
---

# Fundamentos de visión por computadora

Usala para encarar un problema de visión antes de elegir las skills específicas de NVIDIA (DeepStream, TAO, Metropolis, VSS).

## 1. Definir la tarea
Clasificación · detección (cajas) · segmentación (semántica o de instancias) · pose · seguimiento (tracking) · OCR · conteo · detección de anomalías · descripción de video con un VLM.

## 2. Datos
- Cantidad y variedad (iluminación, ángulos, clima, cámaras); clases balanceadas.
- Etiquetado consistente con una guía escrita; separar train/val/test sin fugas (las mismas escenas en un solo split).
- Aumentación acorde al dominio; datos sintéticos (Omniverse Replicator) para los casos raros.

## 3. Modelo
- Empezar con un modelo preentrenado y hacer fine-tuning (TAO Toolkit, Ultralytics, torchvision); comparar con una línea base simple.
- Elegir por precisión vs. latencia según el hardware de destino.

## 4. Métricas
- Clasificación: accuracy, precisión, recall y F1 por clase, matriz de confusión.
- Detección: mAP@0.5 y mAP@0.5:0.95, IoU; segmentación: mIoU, Dice; tracking: MOTA e IDF1.
- Medir latencia (ms por frame) y throughput (FPS) en el hardware real.

## 5. Despliegue
- Optimizar con TensorRT (FP16 o INT8 con calibración); pipelines de video con DeepStream; edge con Jetson.
- Monitorear la deriva de los datos y re-entrenar con los casos fallidos.

## 6. Privacidad y ética
- Minimizar datos personales: difuminar rostros y patentes cuando no hacen falta, retención acotada, base legal para captar imágenes.
- Evaluar sesgos por grupo demográfico en tareas sobre personas.

Fuentes: Szeliski, *Computer Vision: Algorithms and Applications* (2.ª ed.); documentación de NVIDIA TAO, DeepStream y TensorRT.
