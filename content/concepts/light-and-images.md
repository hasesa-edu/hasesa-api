---
title: Light and images
summary: Light travels in straight lines, so a tiny hole can paint an upside-down picture, and similar triangles tell you how big it will be.
status: ai-draft
public: true
curriculum:
  - { subject: physics, grade: 10, unit: "Light" }
  - { subject: mathematics, grade: 9, unit: "Similar figures" }
problems:
  - id: why-upside-down
    type: mcq
    q: "Why is the image in a pinhole camera upside down?"
    choices: ["The hole bends the light", "Light from the top of the object travels in a straight line through the hole and lands at the bottom of the screen", "The screen reflects the image", "Light travels upwards inside the box"]
    answerIndex: 1
    explanation: "Light travels in straight lines. A ray from the top of a tree goes down through the hole and carries on to the bottom of the screen. A ray from the bottom goes up to the top. The rays cross at the hole, so the image is flipped."
  - id: image-height
    type: numeric
    q: "A tree 6.0 m tall stands 30 m from a pinhole camera. The screen is 0.20 m behind the hole. How tall is the image of the tree?"
    answer: 4
    tolerancePct: 2
    unit: "cm"
    explanation: "Similar triangles: image height ÷ object height = image distance ÷ object distance. h = 6.0 m × 0.20 ÷ 30 = 0.040 m = 4 cm."
  - id: find-the-height
    type: numeric
    q: "A building's image in your pinhole camera is 3.0 cm tall. The screen is 15 cm behind the hole, and you are standing 50 m from the building. How tall is the building?"
    answer: 10
    tolerancePct: 2
    unit: "m"
    explanation: "Rearrange h_o ÷ d_o = h_i ÷ d_i to h_o = h_i × d_o ÷ d_i. Work in metres: h_o = 0.030 × 50 ÷ 0.15 = 10 m."
  - id: longer-box
    type: mcq
    q: "You make the pinhole camera box twice as long, keeping the same hole. What happens to the image?"
    choices: ["Twice as big and dimmer", "Twice as big and brighter", "Half as big and dimmer", "It stays the same"]
    answerIndex: 0
    explanation: "The image height is proportional to the screen distance, so it doubles. The same light from the hole is spread over a bigger picture (four times the area), so it gets dimmer."
  - id: bigger-hole
    type: mcq
    q: "You make the pinhole bigger. What happens to the image?"
    choices: ["Brighter but blurrier", "Dimmer but sharper", "Bigger", "It turns the right way up"]
    answerIndex: 0
    explanation: "A bigger hole lets in more light, so the image is brighter. But each point of the object now makes a small disc of light instead of a dot, and the discs overlap, so the image blurs."
  - id: magnification
    type: numeric
    q: "A candle flame 4 cm tall is 20 cm in front of a pinhole. Its image is 10 cm tall. How far behind the hole is the screen?"
    answer: 50
    tolerancePct: 2
    unit: "cm"
    explanation: "d_i = d_o × h_i ÷ h_o = 20 cm × 10 ÷ 4 = 50 cm. The image is bigger than the flame, because the screen is further from the hole than the flame is."
---
Look at the shade under a tree on a sunny day. Among the leaves' shadows you'll see little round spots of light, all the same shape. Each one is a picture of the Sun, made by a tiny gap between the leaves. You can use the same trick to make a camera with no lens at all.

## Light travels in straight lines

In air, light goes in straight lines, called **rays**. That's why shadows have sharp edges, and why you can't see round a corner. Every point on a lit object sends rays out in all directions.

## How a pinhole makes a picture

Put a tiny hole in the front of a dark box, and a screen (tracing paper) at the back.

- From each point on the object, only **one narrow bundle** of rays gets through the hole.
- That bundle lands on **one spot** on the screen.
- Every point on the object lands on its own spot, so the spots together make a picture.

A ray from the **top** of a tree goes **down** through the hole and lands at the **bottom** of the screen. Rays from the left land on the right. The image is **upside down and back to front**.

## How big is the image? Similar triangles

Draw the ray from the top of the object and the ray from the bottom. They cross at the hole and make two triangles: a big one outside the box and a small one inside. The two triangles have the same angles, so they are **similar**: every side is scaled by the same amount.

$$\frac{h_i}{h_o} = \frac{d_i}{d_o}$$

- $h_o$ is the object's height and $d_o$ its distance from the hole,
- $h_i$ is the image's height and $d_i$ the distance from the hole to the screen.

The fraction $\frac{h_i}{h_o}$ is the **magnification**. Use the same units on both sides of each fraction.

## Worked example: measure a tree without climbing it

The image of a tree is 2.5 cm tall on a screen 20 cm behind the hole. You are 40 m from the tree. Rearrange to make $h_o$ the subject:

$$h_o = \frac{h_i \times d_o}{d_i} = \frac{0.025 \times 40}{0.20} = 5 \text{ m}$$

## Brightness against sharpness

- A **smaller hole** gives a sharper image, because each point of the object makes a smaller spot. But it lets in less light, so the image is dimmer.
- A **bigger hole** gives a brighter image but a blurrier one, because the spots spread out and overlap.
- A **longer box** gives a bigger image, but the same light is spread over more area, so it is dimmer.

A lens solves this: it lets in lots of light through a wide opening and bends all the rays from one point back to a single point. That is how the camera in a phone, and the lens in your eye, give pictures that are both bright and sharp.

## Never look at the Sun

A pinhole is the **safe** way to watch the Sun, for example during an eclipse: you look at the image on the screen, with your back to the Sun. Never look at the Sun directly, or through the hole.
