# M&A Renewable Deal Tracker v2 – Auto-fed Open Sources

Esta v2 consulta fuentes abiertas online cada vez que se abre una nueva sesión de la app y extrae candidatos de transacciones M&A renovables para España y compañías españolas en el exterior.

## Fuentes incluidas

- GDELT 2.0 DOC API: no requiere API key.
- Scraping ligero de búsquedas públicas de pv magazine España.
- NewsAPI opcional: requiere `NEWSAPI_KEY` en Streamlit secrets.
- GNews opcional: requiere `GNEWS_API_KEY` en Streamlit secrets.

## Instalación local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Despliegue en Streamlit Cloud

1. Sube `app.py`, `requirements.txt`, `deals_database.csv` y este `README.md` a GitHub.
2. En Streamlit Cloud selecciona:
   - Repository: tu repositorio
   - Branch: `main`
   - Main file path: `app.py`
3. Pulsa Deploy.

## Actualización automática

La app consulta las fuentes online al iniciar una nueva sesión. Además, incorpora un botón en la barra lateral: `Refrescar fuentes online ahora`.

## Importante sobre calidad de datos

La app no debe tratar los datos extraídos automáticamente como confirmados. Por defecto, los registros online se marcan como `pending_review`. Revisa la fuente, valida comprador/vendedor/MW/importe y exporta la base depurada.

## API keys opcionales

En Streamlit Cloud, añade secrets:

```toml
NEWSAPI_KEY = "tu_clave"
GNEWS_API_KEY = "tu_clave"
```

Si no añades claves, la app sigue funcionando con GDELT y pv magazine.
