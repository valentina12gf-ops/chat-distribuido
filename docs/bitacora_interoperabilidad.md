# Bitácora de interoperabilidad

**Proyecto:** Chat distribuido entre grupos  
**Universidad:** Universidad Industrial de Santander (UIS)  
**Integrantes:** Marly Riaño y Carol Gutiérrez  
**Servidor principal:** g1  
**Entorno:** GitHub Codespaces, Docker Compose y Python 3.12

## 1. Pruebas realizadas en entorno local

Se realizaron pruebas de funcionamiento utilizando dos servidores de grupo (`g1` y `g1b`) conectados mediante un servidor central simulado (`mock-central`).

**Resultados:**

- El servidor `g1` respondió correctamente a `/fed/health`.
- El cliente permitió enviar y visualizar mensajes.
- El reloj de Lamport avanzó de 0 a 2 después de dos mensajes.
- Los mensajes permanecieron almacenados después de reiniciar el servidor.
- El servidor `g1b` recibió mensajes enviados desde `g1`, conservando sus identificadores.
- El script `tests/prueba_local.py` finalizó con `RESULTADO: TODO OK`.

## 2. Hallazgos

### Fallas propias y su causa

Durante las pruebas automáticas locales no se reportaron fallos.

Se comprobó el funcionamiento de la persistencia, la deduplicación, los reintentos y la recuperación de mensajes.

### Fallas ajenas (otros grupos / central) y su explicación

**Pendiente:** todavía no se ha realizado la sesión oficial de interoperabilidad con el servidor central del curso y otros grupos.

Las pruebas disponibles se realizaron con un servidor central simulado.

### Incompatibilidades de protocolo detectadas

No se identificaron incompatibilidades durante las pruebas locales automatizadas.

Esto no garantiza la compatibilidad con implementaciones externas, que deberá comprobarse en la sesión oficial.

## 3. Experimento de recuperación

Se realizaron tres repeticiones con una interrupción de 10 segundos y 20 mensajes por repetición, a una tasa de 5 mensajes por segundo.

| Repetición | Recuperación | Perdidos | Duplicados |
|---|---|---|---|
| 1 | 0,46 s | 0 | 0 |
| 2 | 0,54 s | 0 | 0 |
| 3 | 0,57 s | 0 | 0 |

**Resultados generales:**

- Recuperación promedio: 0,52 segundos.
- Mensajes perdidos: 0.
- Mensajes duplicados: 0.
- Desviación estándar aproximada: 0,06 segundos.

Los resultados están disponibles en `experiment/resultados.csv` y `experiment/grafica_recuperacion.png`.

## 4. Sesión oficial de interoperabilidad

**Estado:** pendiente.

Durante la sesión se deberá registrar:

- Comunicación en la sala global `#general` con otros grupos.
- Orden de recepción de los mensajes.
- Comportamiento durante la caída de un servidor.
- Recuperación del historial al reconectarse.
- Fallas e incompatibilidades observadas y sus causas.

## 5. Conclusiones para el póster

Las pruebas locales demostraron que el sistema permite intercambiar mensajes entre dos servidores mediante un servidor central simulado.

El mecanismo de persistencia permitió conservar los mensajes después de reiniciar el servidor.

En el experimento de recuperación se obtuvo un tiempo promedio de 0,52 segundos, sin pérdidas ni duplicados detectados.

Los resultados respaldan el funcionamiento del prototipo en el entorno local. La interoperabilidad con el servidor central real del curso queda pendiente de validación.
