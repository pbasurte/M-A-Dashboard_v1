# M&A Renewable Deal Tracker – Spain & Spanish Companies Abroad

Aplicación en Streamlit para consultar, filtrar, comparar y analizar transacciones de M&A de activos/compañías renovables en España y operaciones internacionales con compañías españolas.

## Instalación

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Archivos incluidos

- `app.py`: aplicación Streamlit completa.
- `sample_deals.csv`: dataset ficticio de ejemplo. No contiene operaciones reales.
- `requirements.txt`: dependencias mínimas.
- `README.md`: instrucciones de uso.

## Uso de datos reales

1. Prepara un CSV o Excel con las columnas indicadas en la pestaña **Upload & Export**.
2. Si faltan columnas, la app las creará vacías para evitar errores.
3. Sube el archivo desde la barra lateral.
4. Revisa la pestaña **Data Quality** para identificar importes no divulgados, MW ausentes, fuentes incompletas, posibles duplicados y anomalías de precio/MW.

## Nota importante

El archivo `sample_deals.csv` contiene exclusivamente datos ficticios marcados como `sample data` y `unverified`. Para cualquier análisis profesional, sustituye el dataset por información real verificada desde fuentes públicas, bases privadas o documentación transaccional.

## Funcionalidades principales

- Executive dashboard con KPIs financieros y operativos.
- Screener de deals con selección mediante checkboxes.
- Vista detallada de cada operación.
- Comparador de transacciones seleccionadas.
- Market analytics con gráficos Plotly.
- Mapa de activos con coordenadas.
- Valuation benchmarking por tecnología, fase y país, excluyendo outliers.
- Strategic insights: compradores activos, vendedores recurrentes, liquidez por tecnología, regiones más activas, distressed potencial y tendencias de precio/MW.
- Data quality checks.
- Exportación a CSV, Excel y Markdown.
