---
title: Levers and moments
summary: Why a long plank lets a child lift an adult, and the simple rule that balances every see-saw.
status: ai-draft
public: true
curriculum:
  - { subject: physics, grade: 9, unit: "Force and motion" }
  - { subject: physics, grade: 10, unit: "Work, energy and power" }
problems:
  - id: moment-calc
    type: numeric
    q: "You push down with 50 N on the end of a spanner, 0.30 m from the centre of the nut. What is the moment of your push?"
    answer: 15
    tolerancePct: 1
    unit: "N m"
    explanation: "Moment = force × perpendicular distance from the pivot = 50 N × 0.30 m = 15 N m."
  - id: seesaw-balance
    type: numeric
    q: "On a see-saw, a child weighing 300 N sits 2.0 m from the pivot. How far from the pivot on the other side must an adult weighing 750 N sit to balance?"
    answer: 0.8
    tolerancePct: 2
    unit: "m"
    explanation: "Balanced means anticlockwise moment = clockwise moment: 300 N × 2.0 m = 750 N × d. So d = 600 ÷ 750 = 0.8 m. The heavier person sits closer to the pivot."
  - id: bucket-effort
    type: numeric
    q: "A plank rests on a brick as a pivot. A 200 N bucket of sand hangs 0.25 m from the pivot. You push down on the other end, 1.5 m from the pivot. What force do you need to just lift the bucket?"
    answer: 33.3
    tolerancePct: 2
    unit: "N"
    explanation: "Effort × 1.5 m = 200 N × 0.25 m = 50 N m. Effort = 50 ÷ 1.5 ≈ 33.3 N, about a sixth of the bucket's weight."
  - id: mechanical-advantage
    type: numeric
    q: "A lever lifts a 600 N load when you push with 150 N. What is its mechanical advantage?"
    answer: 4
    tolerancePct: 1
    explanation: "Mechanical advantage = load ÷ effort = 600 N ÷ 150 N = 4. The lever multiplies your force by 4."
  - id: what-you-pay
    type: mcq
    q: "Your lever lets you lift a load with a quarter of the force. What do you pay for that?"
    choices: ["Nothing: the lever makes free energy", "Your end must move four times as far as the load", "The load becomes lighter", "The lever must be made of metal"]
    answerIndex: 1
    explanation: "Work = force × distance. A quarter of the force over four times the distance is the same work. Levers trade distance for force; they never give you extra energy."
  - id: lever-class
    type: mcq
    q: "In a wheelbarrow, the wheel is the pivot, the load sits in the middle and you lift the handles at the far end. Which class of lever is it?"
    choices: ["First class: pivot in the middle", "Second class: load in the middle", "Third class: effort in the middle"]
    answerIndex: 1
    explanation: "The load is between the pivot (wheel) and the effort (handles), so it is a second-class lever. The effort is always further from the pivot than the load, so it always multiplies your force."
---
A child can lift an adult on a see-saw. A short person can lift a heavy rock with a long pole and a stone. Neither is stronger than the load: they are using a **lever**.

## Pivot, load and effort

Every lever has three parts:

- the **pivot** (or fulcrum): the point it turns about, such as the brick under a plank,
- the **load**: the weight you want to move,
- the **effort**: the force you push or pull with.

## The turning effect: moments

A force turns things more when it acts further from the pivot. That is why a door handle is on the side away from the hinges, and why a long spanner undoes a stiff nut.

The turning effect is called the **moment** of the force:

$$\text{moment} = F \times d$$

- $F$ is the force in newtons (N),
- $d$ is the **perpendicular** distance from the pivot to the line of the force, in metres (m),
- the moment is measured in newton metres (N m).

A weight of 1 kg pulls down with about 10 N (more exactly 9.8 N).

## The law of the lever

A lever is balanced when the moments turning it one way equal the moments turning it the other way:

$$F_1 \times d_1 = F_2 \times d_2$$

This is the **principle of moments**. If the two sides aren't equal, the lever turns towards the side with the bigger moment.

## Worked example: lift the bucket

A 20 kg sack of sand weighs about 200 N. It hangs 0.25 m from the pivot. How hard must you push down 1.5 m from the pivot on the other side?

$$F \times 1.5 = 200 \times 0.25 = 50$$
$$F = \frac{50}{1.5} \approx 33 \text{ N}$$

You push with about a sixth of the weight, because your hand is six times further from the pivot.

## Mechanical advantage, and what it costs

$$\text{mechanical advantage} = \frac{\text{load}}{\text{effort}}$$

In the example it is $200 \div 33 \approx 6$. But look at how far things move: when the bucket rises 5 cm, your hand goes down 30 cm. A lever trades **distance for force**. The work you do (force × distance) is never less than the work done on the load. In real levers it is a little more, because of friction and the weight of the plank.

## Three classes of lever

| Class | What is in the middle | Examples | Multiplies |
|---|---|---|---|
| First | the pivot | see-saw, crowbar, scissors | force or distance, depending on where the pivot is |
| Second | the load | wheelbarrow, bottle opener, nutcracker | force |
| Third | the effort | tweezers, your forearm, a broom | distance and speed |

Your forearm is a third-class lever: the biceps pulls close to the elbow, so it needs a big force, but your hand moves fast and far.
