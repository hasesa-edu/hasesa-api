# Spin Motor: guide's notes

These notes are for the guide only. The module is one 2-hour session for up to 16 students, in teams of two (each student builds their own coil, teams share a battery and magnet). Any table indoors will do. The timing is tight, so do all the preparation below before the session starts.

---

## Before the session

### 1. Shopping

| Item | How many | Notes |
|---|---|---|
| Enamelled copper wire, 0.5–0.7 mm | About 1 m per student, plus 5 m spare | Motor-rewinding workshops in Merkato sell it by weight. Thinner wire (0.3 mm) is too floppy to hold its shape; thicker than 0.8 mm is too heavy. |
| D cells | 1 per team, plus 4 spares | Alkaline if you can. They run down fast with this circuit, so bring fresh ones. |
| Large metal paper clips | 2 per team, plus 10 spares | Not plastic-coated. |
| Magnets | 1 strong magnet (or 2–3 neodymium discs) per team | Ceramic magnets from dead loudspeakers work well; ask electronics repair shops. Neodymium discs, 12–20 mm, are better but need care. You need **at least one neodymium disc per team for the warm-up motor**, because ceramic magnets don't conduct electricity. |
| Compasses | 1 per team | |
| Insulated thin wire | 2 m per team | Bell wire or telephone wire. |
| Iron nails, 7–10 cm, and small paper clips | 1 nail per team, a box of clips | Check with a magnet that the nails are iron (they stick). |
| Bare copper wire | 15 cm per team | Strip a scrap of 1.5 mm² single-core house wiring. |
| Fine sandpaper, rubber bands, modelling clay | | |
| Optional: toy DC motor, multimeter | 1 of each for the class | |

### 2. Prepare

- **Build and test your demo motor** the day before (see step 3 for the method). Bring a spare coil in case it gets bent.
- **Strip** 2 cm of insulation from both ends of each piece of insulated wire.
- **Cut** the enamelled wire into 1 m lengths, one per student, plus spares.
- **Wind one spare coil per team**, already scraped correctly. A student whose own coil won't work after 10 minutes can test their supports with a known-good coil, which tells them whether the problem is the coil or the supports.
- **Check every battery** by running your demo motor on it for a few seconds.
- Keep neodymium magnets in a box with cardboard between them, not stacked loose.

---

## Safety briefing (read aloud in step 1)

- One 1.5 V cell only. Never mains, never a car or motorbike battery. Say why: a car battery can push hundreds of amps through a bare wire, enough to make it glow and burn skin.
- The motor and all the warm-up circuits are nearly a **short circuit**: a bare wire straight across the battery. A few amps flow, so the wire and the battery get hot. **10 seconds at most**, then disconnect. Pick up wires by their insulation, or wait.
- Neodymium magnets: slide them apart, never pull straight. Keep fingers out of the gap. Keep them away from phones, bank cards and the compasses (they can re-magnetise a compass needle the wrong way).
- Magnets never go in mouths. Count magnets out and back in at the end.
- Sandpaper only. If enamel won't come off, you scrape it with a blade, away from the students.

---

## Session plan

### Step 1: The spinning coil (15 min)

Read the rules first (5 minutes). Then show your motor. Do these in order and let them watch:

1. Flick it. It spins.
2. Lift one leg off its clip. It slows and stops: no current, no spin.
3. Put it back, then take the magnet away. It stops: no magnet, no spin.
4. Turn the magnet over. It spins the other way (you may need to flick it the other way).

Don't explain anything. Collect predictions. If a student says "the wire is magnetic", ask them to try a paper clip against a piece of copper wire.

### Step 2: Current makes magnets (35 min)

**Warm-up motor (5 min).** This uses the neodymium magnet as part of the circuit: current flows from the + top, down the copper wire, through the magnet's metal coating into the − end. The magnet's field pushes sideways on the current in the wire, so it spins. It won't work with a ceramic magnet (ceramic doesn't conduct). If the wire doesn't spin: it must touch the + bump and lightly brush the magnet's side, and be roughly balanced. Flipping the magnet reverses the spin.

**Compass and wire (8 min).** The wire must lie **along** the needle (north–south), right on top of the compass. A wire lying east–west makes a field along the needle and you see almost nothing. Expected: a big swing, often 45° or more, which reverses when the battery is reversed. With the wire 5 cm above, the swing is much smaller.

Answer key, if they ask which way: with the current flowing **north** in a wire **above** the compass, the north end of the needle swings **west**. With the wire under the compass, it swings east.

Worked numbers for curious students: with about 3 A, the field 1 cm from the wire is $B = \dfrac{\mu_0 I}{2\pi r} = \dfrac{(4\pi \times 10^{-7})(3)}{2\pi(0.01)} = 6 \times 10^{-5}$ T, about twice the horizontal part of the Earth's field in Addis (roughly $3.5 \times 10^{-5}$ T). That's why the swing is so big. At 5 cm the wire's field is five times weaker.

**Theory (7 min).** Point them to the two named parts of *Electromagnetism* and the Current section of *Charge, current and voltage*. They don't need to read everything now.

**Electromagnet (12 min).** Typical results with a D cell: 20 turns on a nail lifts a few small clips; 40 turns lifts noticeably more; the coil with no nail lifts almost nothing. Exact numbers depend on the battery and how tightly they wind. The pattern is what matters: more turns, more current, and an iron core all make it stronger. If 40 turns is weaker than 20, they probably wound the second layer in the opposite direction, which cancels the first.

Where students get stuck: holding the wire ends on the battery and dipping the nail at the same time. Partners help: one holds the battery, one dips.

**Expected record answers.** A current makes a magnetic field around it. More turns and the iron nail made it stronger. The heat came from the battery's chemical energy: the charge flowing through the wire gives up its energy as heat.

### Step 3: Build the motor (45 min)

**Winding.** Common faults: legs not in line with each other, legs not through the centre of the coil, coil loose. A wobbling coil bounces off its supports and loses contact. Have them spin it between their fingertips before they scrape anything.

**Scraping: the key idea.** Leg 1 must be bare all round. Leg 2 is sanded only on the **top half while the coil stands upright like a wheel**. Here is why the orientation matters:

- The coil feels no turning push when it lies **flat** over the magnet (its plane horizontal), and the biggest push when it stands **upright**.
- The push changes direction each time the coil passes the flat position.
- So the current must switch on and off as the coil passes **flat**. With the leg sanded as above, the bare half touches the bottom of the paper-clip loop for exactly the half-turn between one flat position and the next.

If a student sanded the top half while the coil lay flat, the switching happens at the wrong moments and the coil only rocks. Fix: sand again in the right place, or make a new coil. If they sanded the bottom half instead of the top, the motor still works; it just spins the other way.

**If both legs are fully scraped**, the coil swings round, overshoots a little, rocks, and settles flat over the magnet, with its own field lined up with the magnet's. It's a compass needle, not a motor. Let a curious student try it with a spare coil.

**Supports.** Paper-clip loops must be smooth, level and bare (some clips have a coating: sand the loops). Height: 5–10 mm between the bottom of the coil and the magnet.

**Expected result.** By the end of 15 minutes of testing, most coils spin. It usually needs a flick to start. Reversing the battery or flipping the magnet reverses the direction of spin.

### Step 4: Faster, and why (25 min)

**Speed challenge.** A stronger magnet and a smaller gap make the biggest difference. More turns makes a stronger coil-magnet but a heavier coil with more resistance, so it doesn't always help: an honest result either way is fine, as long as they changed one thing at a time.

**Answer key for the numbers.**

1. $F = BIL = 0.05 \times 2 \times 0.225 = 0.0225$ N, about 0.02 N.
2. $W = mg = 0.002 \times 9.8 = 0.0196$ N, about 0.02 N. The push is about the same as the coil's weight. That's plenty: the paper clips hold the weight up, so the push only has to beat a little friction.
3. $Q = It = 2 \times 10 = 20$ C. $E = QV = 20 \times 1.5 = 30$ J. Thirty joules every 10 seconds, almost all of it heat: that's why the wire gets warm and why the battery runs down in an hour or so of use.

These are estimates. Stress that the real field and current vary a lot from motor to motor.

**Motor as generator (optional).** Spinning a toy motor's shaft by hand gives a few tenths of a volt on the multimeter, more when spun faster. Reversing the direction reverses the sign. Link: a motor turns current into motion; a generator turns motion into current; it's the same machine.

**Explain to the guide.** Do the sign-off conversations during the speed challenge, two students at a time.

---

## Troubleshooting

| Problem | Likely cause and fix |
|---|---|
| Coil doesn't move at all | No current. Leg 1 not bare all round, paper-clip loops coated, or a flat battery. Test with the spare coil. |
| Coil rocks but won't go round | Leg 2 sanded in the wrong place, or both legs fully bare. Re-sand leg 2 with the coil upright, or use a new coil. |
| Spins a few turns then stops | Coil unbalanced, or legs rubbing. Straighten the legs and check they are in line. Bring the magnet closer. |
| Coil jumps off the supports | Loops too big or not level. Bend smaller loops; flatten the battery with clay. |
| Very slow, battery warm | Battery running down. Swap in a fresh cell and let the old one rest. |
| Warm-up motor doesn't spin | Ceramic magnet (needs neodymium), or the wire isn't touching the magnet. |
| Compass hardly moves | Wire lying east–west instead of along the needle, or held too high. |

---

## Judging the sign-off items

- **spins:** at least 5 seconds of continuous spinning on two tries. A flick to start is fine. It must be the student's own coil.
- **commutator:** they must say the current is switched **off** for half of each turn, and why that matters (the push would act backwards for that half). "It makes it work" isn't enough.
- **force-on-current:** a current in a magnetic field feels a push; reversing the current or flipping the magnet reverses it. Bonus if they mention $F = BIL$.
- **faster:** a short record of at least two changes, one at a time, with the result of each.
- **safety:** short runs, disconnecting between tries, magnets handled carefully. If they needed one reminder and then kept to it, that's fine; if not, talk it through before signing.

---

## Notes for experts reviewing this draft

- The field value $B \approx 0.05$ T at the coil and current $I \approx 2$ A are rough estimates for a ceramic magnet with a gap of a few millimetres and an alkaline D cell with paper-clip contacts. A measured current (10 A range on a multimeter) and a measured field would make the worked numbers more honest.
- The Earth's horizontal field in Addis is given as roughly 35 µT; please check against a current geomagnetic model.
- The $F = BIL$ estimate counts only the bottom of each turn and ignores the weaker opposite push on the top of each turn. It's an order-of-magnitude check, not a model of the torque.
- Confirm where enamelled wire and neodymium discs are reliably sold in Addis, and current prices.
- Curriculum tags come from the concept units (grade 10 magnetism, grade 11–12 induction); confirm against the current national curriculum.
