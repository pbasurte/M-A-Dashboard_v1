# M&A Renewable Deal Tracker v4 – Master Database + Recent Updates

Esta versión corrige el enfoque anterior: la app ya no intenta reconstruir el histórico completo en runtime. La app carga una base maestra histórica (`deals_master_2020_2026.csv`) y, en paralelo, permite buscar candidatos recientes online.

## Archivos

- `app.py`: aplicación Streamlit estable, database-first.
- `deals_master_2020_2026.csv`: base maestra histórica inicial.
- `recent_candidates.csv`: candidatos recientes pendientes de revisión.
- `sources_config.csv`: fuentes utilizadas/sugeridas.
- `data_dictionary.xlsx`: diccionario de campos.
- `requirements.txt`: dependencias.

## Importante

La base incluida es un **public seed** construido con datos públicos visibles en fuentes abiertas. No debe considerarse exhaustiva. Para tener absolutamente todas las operaciones 2020-2026, debe enriquecerse con exportaciones licenciadas o bases profesionales como Mergr, TTR, Inframation, IJGlobal, LSEG/Mergermarket o una extracción completa/validada de pv magazine/iDeals.

## Ejecución

```bash
pip install -r requirements.txt
streamlit run app.py
```

## GitHub / Streamlit Cloud

Sube todos los archivos a GitHub y en Streamlit Cloud selecciona `app.py` como main file path.

## Flujo operativo

1. La pestaña `Historical Deal Screener` permite seleccionar transacciones históricas.
2. La pestaña `Recent Candidates` permite revisar candidatos recientes detectados online.
3. Los candidatos recientes no se incorporan automáticamente a la base maestra: deben revisarse y cargarse en `deals_master_2020_2026.csv`.
