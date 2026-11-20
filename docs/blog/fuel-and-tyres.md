# Tyres don't get faster with age: separating fuel from wear

*Draft write-up for Pit Wall, an F1 strategy simulator. Numbers are from 90 races, 2023 to 2026.*

Every strategy question in Formula 1 comes down to one trade. A pit stop costs 19 to 28 seconds, depending on the track,
and fresh tyres pay it back by being faster lap after lap. To ask "what if he had stopped eight laps
earlier?" a simulator needs one number above all: how much slower a tyre gets with every lap it
runs. The obvious way to measure it gives the wrong answer almost half the time.

## The obvious way

Take every stint, keep the laps run in clean air with no safety car, pit stop, yellow flag or rain,
and fit a line through lap time against tyre age. The slope is the degradation.

I did that for the 2,316 stints in the data with at least ten clean laps. The median slope is
**+0.006 s per lap**: tyres barely wear at all. And in **44 %** of stints the slope is negative.
Taken at face value, nearly half the field's tyres got faster as they aged.

They didn't. Within a stint, three things change together with every lap:

- the tyre gets older, which makes the car slower;
- the car burns about 1.5 to 1.8 kg of fuel, which makes it faster;
- the track gathers rubber, which makes everyone faster.

A line through one stint cannot tell these apart, because they move in lockstep. Fuel burn-off is
worth about 0.06 s a lap, and real wear is worth about the same, so the fitted slope is roughly
their difference: near zero, and negative whenever fuel wins.

## The decision: make fuel a term of its own

The way out is that the three effects do not always move together. Tyre age **resets** at every
pit stop; fuel and track evolution keep going. A race with two or three stints gives laps where the
car is heavy on new tyres and laps where it is light on old ones. A model that sees the whole race
at once can then separate a race-lap effect (fuel and track, together) from a tyre-age effect
(wear).

So every lap-time model in Pit Wall carries an explicit race-lap fuel term. It has a prior from
physics: about 0.03 s per kilogram, set per regulation era in a config file, not hidden in code. The
model is hierarchical and Bayesian: a wear slope per era and Pirelli C-number, refined per track and
then per team, each level pulled towards the one above. Fitted on 39,041 clean laps from 2023 to
2025, the fuel effect comes out at **0.0291 s/kg**, right next to the physics prior.

With fuel separated, the same 2,316 stints have a median wear slope of **+0.05 s per lap**, and
only **5 %** of them are negative. Tyres wear out after all.

Two details made this work:

- **Compounds are keyed by C-number.** "Soft" is the C3 at one race and the C5 at another; Pirelli
  publishes the allocation per event. Wear belongs to the compound, not to its label.
- **The 2026 cars are a separate era.** New chassis, power units and tyres. Pooling them with
  2023 to 2025 would blend two different cars into one wrong answer.

## Why it matters, and the honest catch

Here is the part I didn't expect. In a leave-one-race-out test, each held-out stint is predicted
from its first three clean laps. The model beats a naive forecast, "every remaining lap equals the
median of those three", only modestly: a mean absolute error of 0.725 s against 0.758 s.

That is the same cancellation again. Fuel and wear roughly offset, so most stints really are close
to flat, and a flat line forecasts them well. Most of what's left is lap-to-lap noise that no pace
model removes.

So why bother? Because a strategy simulator does not forecast stints as they happened. It asks what
happens when a stint is **made longer or shorter**. Stop eight laps earlier, and the next stint's
tyres are eight laps younger at every point, but the fuel curve is exactly the same, because the
race lap is the same. A flat median can't answer that, and neither can a slope that mixes fuel with
wear. Only the separated model can, and that question is the whole point of a strategy tool.

On Hungary 2024, from lap 20, moving Norris's stop from lap 45 to lap 37 finishes ahead of his real
strategy in 16 % of 2,000 simulated races and behind in 28 %. That costs 0.25 places on average.
Both plans see the same safety cars, the same retirements and the same parameter draw in each run,
so the difference is the plan and not the luck. A model with the naive slope of +0.006 s a lap would
say tyres hardly matter, so it barely matters when you stop.

## What it doesn't do yet

Wear is a straight line. The residuals show no curvature even 30 laps into a stint, but teams stop
before a tyre falls off a cliff, so the data may simply not contain one. Rivals also keep their real
strategies; they can't react to yours. Both are listed, with the calibration numbers, in
[the README](../../README.md).

---

Data: [OpenF1](https://openf1.org). Unofficial project, not affiliated with Formula 1.
