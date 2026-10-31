const j = $json;
return {
  json: {
    agent: j.agent,
    tarea: j.prompt,
    model: null,
    output: 'No hay modelos NVIDIA disponibles ahora (todos agotados o con error). Probá de nuevo en unos minutos.',
    fallos_previos: j._router.errors,
    ok: false,
  },
};
