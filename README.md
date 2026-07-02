# M&A Renewable Deal Tracker v5 – Deal Selection Focus

Cambios:

1. Eliminados los gráficos irrelevantes.
2. Corregido `StreamlitDuplicateElementId` con claves únicas y evitando reutilizar elementos repetidos.
3. La barra lateral tiene un único filtro: `Deal`.
4. El desplegable de `Deal` muestra todos los deals e indica si cada uno tiene importe `disclosed` o `undisclosed`.
5. Candidatos recientes separados de la base maestra.

## Uso

Sube este `app.py` al repo junto a:

- `deals_master_2020_2026.csv`
- `recent_candidates.csv`
- `requirements.txt`

Ejecuta:

```bash
pip install -r requirements.txt
streamlit run app.py
```
