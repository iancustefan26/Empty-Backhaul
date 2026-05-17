# Client demo — 3-beat script

A 60-second walkthrough that shows the three things a Cluj-based reefer
carrier actually cares about: a daily plan, the paperwork to be legal,
and the money breakdown.

## Setup (once, the morning of the demo)

```bash
cd backend
bash docs/demo.sh
```

The script reseeds 15 vans + 60 loads anchored to today, brings up
FastAPI on `:8000` and Vite on `:5173`, warms the optimiser cache, and
prints the talk-track with live numbers. Open
[http://localhost:5173](http://localhost:5173) in **incognito**.

## The 3 beats

### Beat 1 — "Plan today's routes"

| | |
|---|---|
| **Type / say** | `Plan today's routes` |
| **What happens** | Sub-second. The chat replies with `"Here is your plan… I prepared 3 options with different profits — €X · €Y · €Z. Option 1 is the best."` Two hero stats appear: today's profit and vans on the road. The map fills with one colour-coded polyline per van — solid for loaded legs, dashed for empty deadhead. |
| **Talking point** | "The dispatcher just asks in plain English. The optimiser ranks 3 alternatives — Option 1 maximises profit; Options 2 and 3 trade margin for SLA coverage or for fewer vans on the road. Click any pill to switch." |

### Beat 2 — Click a route on the map

| | |
|---|---|
| **Click** | Any coloured polyline. A floating panel slides in over the map, the rest of the routes dim. |
| **What happens** | The panel shows three sections: (1) the cargo + shipper with a tap-to-call number, (2) the compliance documents, each tagged `READY` / `VERIFY` / `MISSING` with a citation, (3) total / loaded / empty km + driver hours + margin for that one van. |
| **Talking point** | "The dispatcher sees exactly what's in the truck and exactly what paperwork the driver needs to be legal — CMR consignment note, GDP temperature log for pharma, ANSVSA wash certificate after raw protein, cold-chain trace for frozen. Anything red is a blocker." |

### Beat 3 — "Show me costs and km"

| | |
|---|---|
| **Type / say** | `Show me the estimated costs, total kilometers and empty kilometers` |
| **What happens** | A stats card unfolds in the chat: revenue / total cost / margin (3 hero numbers), then loaded vs empty km with a bar, then today's diesel price + litres burned + fuel cost. |
| **Talking point** | "At today's diesel price (€1.65/L Cluj county) the fleet burns ~X litres for €Y in fuel. Operating cost is €Z, revenue is €R, leaving margin €M — exactly what the dispatcher will see at end-of-day. Without this system the empty km would be 30-40 % higher." |

## Voice note

If the laptop has a mic, click the mic icon and **speak** the prompts —
Web Speech API transcribes in real time. Romanian works too:
`"planifică rutele de azi"` triggers the same plan flow.

## Reset between rehearsals

Click **Clear conversation** at the bottom of the chat panel — wipes
localStorage. The next "Plan today's routes" reseeds the map cleanly.

## Stop

```bash
bash docs/demo-stop.sh
```
