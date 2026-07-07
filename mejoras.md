Con sombrero de arquitecto, esto es lo que veo y propondría — organizado por impacto, no por orden de implementación:

1. Concurrencia: el modelo de threads tiene un techo que no estamos midiendo
MAX_CONCURRENT_STUDIES = 5 limita estudios, pero cada estudio puede abrir hasta 4 threads de portal, y cada uno lanza su propio proceso Chromium vía Playwright. En el peor caso son ~20 navegadores simultáneos — nadie está limitando eso hoy. Propongo un semáforo separado sobre instancias de navegador (no sobre estudios), independiente de MAX_CONCURRENT_STUDIES, para que el límite real sea "cuánta RAM/CPU tiene la máquina", no "cuántos estudios pidió el usuario".

2. SQLite sin WAL
Con el fragment de "Mis Estudios" refrescando cada 5s (lecturas) mientras hilos de fondo escriben (upsert_raw_job, finish_scraping_run), estamos en modo journal por defecto de SQLite, que serializa lector-contra-escritor más de lo necesario. PRAGMA journal_mode=WAL es un cambio de una línea en session.py que deja leer y escribir en paralelo de verdad — con el timeout=30 actual, hoy lo estamos disimulando con reintentos en vez de resolverlo.

3. Duplicación en scraping.py
_scrape_portal y _scrape_portal_fresh_ctx son ~90% el mismo código. Cada vez que agregamos algo al loop (el chequeo de stop_requested, el filtro de fechas, el límite de 7 minutos) lo tuve que tocar dos veces, con riesgo de que se desincronicen. Los unificaría en una sola función parametrizada por estrategia de contexto (closure o clase chica), no dos funciones gemelas.

4. Dos fuentes de verdad sobre capacidades de portal
fresh_context_per_keyword vive como atributo de clase en cada scraper; las notas de "se puede combinar con X" viven en portal_info.py. Son la misma información contada dos veces — ya se desincronizaron una vez (por eso la corrección de la sesión pasada). Los uniría en un solo lugar.

5. dashboard/app.py sigue siendo el cuello de botella de mantenibilidad
1100+ líneas mezclando render de UI, validación y disparo de lógica de negocio. Ya sacamos theme.py/page_state.py/template_cards.py como módulos puros — seguiría ese patrón con la validación del formulario "Nuevo Estudio" y la lógica del fragment de "Mis Estudios", para poder testearlas con pytest en vez de necesitar Playwright cada vez que algo cambia ahí.

6. CLI y dashboard no comparten el mismo camino de ejecución
El CLI llama scraping.run_scraping directo y bloquea; el dashboard pasa por study_runner (cola, hilos, stop). Si alguien corre el CLI y el dashboard contra el mismo sivml.db a la vez, no se coordinan — el CLI puede arrancar un 6to estudio aunque el dashboard ya tenga 5 corriendo. Propongo que el CLI también pase por study_runner.start_or_queue_study, aunque sea de forma síncrona (bloqueando hasta que termine), para que haya un solo punto de verdad sobre cuántos estudios corren.

7. Sin vínculo Study ↔ Template
StudyTemplate no tiene ninguna relación con los Study que generó — hoy la única pista es que el nombre del estudio incluye el nombre de la plantilla como texto. Si en algún momento quieren ver "cómo cambió la demanda de esta plantilla mes a mes" (que es literalmente el propósito de un sistema de vigilancia), no se puede consultar de forma confiable. Agregaría Study.template_id (nullable FK) — barato ahora, doloroso de reconstruir después con datos históricos ya sueltos.

8. Observabilidad
Los errores solo viven en scraping_runs.error_message por fila — no hay vista consolidada de "qué falló últimamente" ni rotación del log del .exe (crece sin límite en una sesión larga). Un RotatingFileHandler es trivial; un panel de "últimos errores" cruzando estudios ya sería una mejora real de soporte.

9. requirements.txt sin fijar versiones
Todo usa >=. Funciona hoy, pero el día que Streamlit o Playwright saquen una versión mayor con breaking changes, el instalador de un usuario nuevo puede romperse sin que nosotros cambiemos una sola línea. Fijaría rangos (>=X,<Y) al menos para streamlit/playwright/sqlalchemy.

No implementé nada de esto — es la lista para que elijas. Si tuviera que priorizar dado el estado actual: #2 (WAL, 1 línea) y #9 (pins, 1 archivo) son gratis y sin riesgo; #1 (semáforo de navegadores) es la que más me preocupa si esto se usa con estudios grandes seguido. ¿Con cuál querés que arranque?