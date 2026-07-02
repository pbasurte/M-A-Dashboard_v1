# M&A Renewable Deal Tracker v3 – Historical Database + Incremental Updates

Esta v3 combina:

1. Base histórica de candidatos de deals desde 2020 o el año que selecciones.
2. Actualización incremental de los últimos 90 días cada vez que se abre la app.
3. Refresco manual tanto del histórico como de las novedades recientes.
4. Selección de operaciones, comparables, exportación y control de calidad.

## Ejecución

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Despliegue en Streamlit Cloud

Sube estos archivos a GitHub:

- app.py
- requirements.txt
- deals_database.csv
- README.md

En Streamlit Cloud:

- Main file path: `app.py`
- Branch: `main`

## Funcionamiento

- Al abrir la app, se actualizan automáticamente los últimos 90 días.
- Para crear la base histórica, pulsa `Construir/actualizar histórico desde fuentes abiertas` en la barra lateral.
- El histórico se obtiene principalmente de GDELT por ventanas trimestrales desde el año inicial seleccionado.
- Los candidatos se marcan como `pending_review` porque la extracción es automática y debe validarse.

## Nota importante

Streamlit Cloud no guarda cambios permanentes en el repositorio cuando la app está corriendo. Por eso, para conservar una base histórica validada debes exportar `deals_database_v3.csv` y subirlo de nuevo al repo como `deals_database.csv`, o conectar una base externa en una fase posterior.
