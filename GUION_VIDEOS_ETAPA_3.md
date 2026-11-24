# GUIONES DE REGISTRO AUDIOVISUAL (ETAPA 3)
## Laboratorio de Sonido 3 — Trabajo Final: Mesa Sonora

Este documento contiene la estructura plano por plano y los parlamentos sugeridos para filmar los dos entregables audiovisuales obligatorios exigidos por la cátedra en la **Etapa 3**:
1. **Video Exhibición / Trailer (1:30 a 2:00 min):** Enfoque artístico y poético, centrado en la experiencia del usuario y la obra funcionando.
2. **Video Técnico / Desglose de Proceso (3:00 a 4:00 min):** Demostración analítica y pedagógica de la arquitectura de software, protocolos y motor DSP.

---

## 1. VIDEO EXHIBICIÓN / TRAILER (Duración: ~1:45 min)

> **Objetivo:** Mostrar la obra montada en penumbras, con la proyección generativa activa de fondo y las manos interviniendo el paisaje sonoro. No requiere locución técnica; se apoya en títulos breves en pantalla y en la evolución dramática del sonido.

```
+-----------------------------------------------------------------------------------------+
| TIEMPO    | PLANO / IMAGEN                             | AUDIO Y ACCIÓN                 |
+-----------+--------------------------------------------+--------------------------------+
| 0:00-0:15 | Plano detalle oscuro de la superficie de   | Silencio absoluto.             |
|           | la mesa. Luz tenue de proyección.          | Entra un murmullo lejano de    |
|           | Título en pantalla:                        | viento abisal (Canal 1).       |
|           | "MESA SONORA: Sonomontaje Bimanual"        |                                |
|           |                                            |                                |
| 0:15-0:35 | Plano medio: Ingresa la mano izquierda.   | Se levanta el meñique y luego  |
|           | La cámara enfoca los dedos abriéndose.    | el anular. Entran el viento y  |
|           | Proyección de fondo: fluidos bioluminis-  | el agua de río en loop fluido. |
|           | centes reaccionan a los dedos.            | Sonido seco y cercano.         |
|           |                                            |                                |
| 0:35-0:55 | Plano cenital (desde arriba):              | La mano izquierda se desplaza  |
|           | Se observa la división virtual de zonas.   | en el eje X: el filtro pasa-   |
|           | La mano izquierda se desplaza hacia la     | bajos se abre, liberando un    |
|           | derecha de su área.                        | torrente de armónicos y aire.  |
|           |                                            |                                |
| 0:55-1:20 | Ingresa la mano derecha en la Zona B.      | Se levanta el índice derecho:  |
|           | Ambas manos activas a la vez.              | entra el canto de aves.        |
|           | La mano derecha se aleja en el eje X.      | La mano derecha envía el audio |
|           | Proyección: interferencias y ondas dobles. | hacia el delay ping-pong: los  |
|           |                                            | pájaros rebotan en eco estéreo.|
|           |                                            |                                |
| 1:20-1:35 | Plano general de la instalación:           | Clímax sonoro. Suenan las 5    |
|           | Usuario inmerso frente a la mesa con el    | capas sumadas con modulación   |
|           | proyector bañando el espacio.              | continua de filtro y resonancia|
|           |                                            | sin distorsión ni saturación.  |
|           |                                            |                                |
| 1:35-1:45 | Las manos se cierran suavemente en puño.   | Fade-out suave de 160 ms.      |
|           | La proyección se disuelve en oscuridad.    | Queda solo una cola de reverb  |
|           | Placa final: Integrantes y Cátedra         | que se apaga en el silencio.   |
|           | Laboratorio de Sonido 3.                   |                                |
+-----------------------------------------------------------------------------------------+
```

---

## 2. VIDEO TÉCNICO / DESGLOSE DE PROCESO (Duración: ~3:30 min)

> **Objetivo:** Demostrar la solidez de la arquitectura ante los docentes. Se graba capturando la pantalla (con OBS o grabador de pantalla) combinando la ventana de Python y el patch de PlugData/Pure Data, con voz en off de los integrantes.

### Bloque 1: Introducción y Devolución del Docente (0:00 - 0:45)
* **Visual:** Pantalla dividida mostrando la cámara en vivo con los esqueletos de MediaPipe a la izquierda y el patch de PlugData a la derecha.
* **Locución (Integrante 1 o 2):**  
  *"Hola a todos. En esta entrega de Laboratorio de Sonido 3 presentamos la Mesa Sonora. A partir de la devolución de la cátedra en la etapa anterior, donde nos señalaron la artificialidad de simular instrumentos tradicionales de orquesta, tomamos una decisión de diseño fundamental: migramos el proyecto hacia el campo de la Ecología Acústica y el Sonomontaje. En lugar de sintetizadores senoidales, trabajamos con grabaciones reales de campo en alta fidelidad: viento, río, grillos, aves y plantas."*

### Bloque 2: Arquitectura y Separación de Responsabilidades (0:45 - 1:30)
* **Visual:** Zoom sobre la ventana de terminal y la consola de PlugData donde se ve el puerto UDP `9000`.
* **Locución (Integrante encargado de Visión/Python):**  
  *"Una premisa obligatoria de nuestro diseño es la estricta separación de tareas: Python no reproduce audio ni toca la placa de sonido; se dedica exclusivamente a la captura de cámara a 60 cuadros por segundo mediante la red neuronal MediaPipe HandLandmarker. Extrae 42 puntos articulares y calcula la biomecánica de los 10 dedos. Toda la telemetría se empaqueta en sockets UDP locales hacia el puerto 9000. Por su parte, PlugData es el motor acústico exclusivo: recibe los paquetes con `[netreceive -u 9000]` y los distribuye mediante `[route]` hacia los reproductores."*

### Bloque 3: Demostración en Vivo del Doble Deck y DSP (1:30 - 2:45)
* **Visual:** Se muestra el cursor y las manos del operador interactuando frente a la cámara mientras se observa cómo reaccionan los objetos en Pure Data.
* **Locución (Integrante encargado de DSP/Pure Data):**  
  1. **Disparo de Capas:** *"Como pueden ver en el patch, cada canal cuenta con un módulo `[readsf~ 2]` estéreo con loop automático por compuerta `[spigot]`. Cuando el usuario levanta un dedo, una rampa de 160 milisegundos en `[line~]` enciende el audio suavemente sin clics digitales."*
  2. **Zona A (Filtro y Tono):** *"La mesa se divide en dos zonas operativas. En la Zona Izquierda (Deck A), al desplazar la mano horizontalmente, enviamos `deck_a X Y`. Observen cómo el objeto `[lop~]` barre de forma continua desde 180 Hz hasta 14.000 Hz, cambiando la acústica de un ambiente velado o sumergido a uno cristalino."*
  3. **Zona B (Delay Ping-Pong y Canon):** *"En la Zona Derecha (Deck B), el interactor puede activar las mismas capas para generar un diálogo espacial. El eje X de esta mano modula en tiempo real la realimentación cruzada de dos memorias de retardo `[delwrite~]` de 320 ms y 460 ms, creando una espacialidad expansiva."*
  4. **Protección de Salida:** *"Toda la suma confluye en un bus maestro con atenuación dinámica y un limitador `[clip~ -0.95 0.95]` para garantizar que, incluso con los 10 canales activos, la señal nunca sature la salida `[dac~]`."*

### Bloque 4: Conclusiones y Puesta en Escena (2:45 - 3:30)
* **Visual:** Se muestra la 2da ventana de arte visual generativo (fluidos en tiempo real) y el montaje físico de la mesa con la cámara.
* **Locución (Director de montaje / Bitácora):**  
  *"Complementando el sonido, el sistema ejecuta una segunda ventana independiente con renderizado de fluidos y advección en tiempo real, diseñada para proyectarse en pantalla completa mediante la tecla `[P]`. Esto transforma la mesa sonora en una experiencia multidisciplinar inmersiva, cumpliendo con los objetivos conceptuales y técnicos de Laboratorio de Sonido 3. Muchas gracias."*
