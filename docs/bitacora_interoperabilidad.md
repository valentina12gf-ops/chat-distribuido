# Bitácora — Sesión de interoperabilidad

- **Fecha:** ____
- **Grupo:** gN — Marly Riaño, Carol Gutiérrez
- **Integrantes presentes:** ____

## Antes de la sesión
- [ ] `.env` con `GROUP_NAME` y `PUBLIC_URL` visible en la red de la sala.
- [ ] `CENTRAL_URL` apuntando al central del profesor.
- [ ] `docker compose up --build` funciona en un equipo limpio.
- [ ] Salida del script de conformidad guardada en `docs/salida_conformidad.txt`.

## Prueba 1: conversación global
| Qué verificamos | Resultado | Evidencia (log / captura) |
| --- | --- | --- |
| Un usuario de cada grupo escribió en #general | | |
| Todos vimos los mensajes de todos | | |
| El orden (lamport, origin) coincide entre servidores | | |

Observaciones:

## Prueba 2: caída y recuperación
| Qué verificamos | Resultado | Evidencia (log / captura) |
| --- | --- | --- |
| Apagamos nuestro servidor mientras otros escribían | | |
| Al volver recuperamos lo perdido (`HISTORY` en el log) | | |
| No aparecieron duplicados | | |

Observaciones:

## Hallazgos
### Fallas propias y su causa
1.
### Fallas ajenas (otros grupos / central) y su explicación
1.
### Incompatibilidades de protocolo detectadas
1.

## Conclusiones para el póster
