# Fable verification pass, 2026-10-23 ~13:20. Open items to fix

Results: pytest 126, base 84/84, face 35/35, CAD checks 15/15. The items below are things those checks
don't look at.

1. **The head can't be assembled (B3).** Neither half can slide closed. Three millimetres from home,
   the halves already hit the hub flanges and the frame plates. The plates run down to axis −20 and
   the flanges to −23, trimmed only by the underside cone, which clears just in the final position.
   The ear-servo shaft hole (X = −6, R3.5) is crossways to the slide. The rear-top posts at
   (−47, ±30) sit on the 30 mm fillet, and the counterbore eats the wall there.
   *Fix:*
   - trim the plates with a flat plane at axis −10 and the flanges at −13, making the hub hole a U-slot covered by the flange;
   - notch the ear-shaft hole out to the X = 0 edge (hidden by the ear hub);
   - move the posts to about (−20, ±50), on the flat top outside the Ø100 mic board;
   - **add a slide-assembly check to build.py** that moves each half along X from 0 to 80 mm and checks for clashes.
2. **Bumper travel is only 1.5 mm, and there are no working return springs (B2).**
   - The bumper's inner wall (r 115) hits the chassis rim (113.5) after 1.5 mm.
   - Its ends hit the rear skirt at 2 mm (the split gap is 2 mm).
   - The spring pocket floor is 18 mm from the bumper, so a 12 mm spring never touches.
   - The sleeves are 3 mm long, the same as the lug, so the screw clamps the lug.
   - The switch holes are radial, so the button doesn't face the striker.

   *Fix:*
   - cut the chassis rim back 3 mm on the front arc;
   - make the split gap ≥ 4 mm;
   - use 20 mm springs, or put the pocket on the striker;
   - use 3.5 mm sleeves;
   - turn the switch so its button faces the striker;
   - add a bumper-travel check (move the bumper −X by BUMPER_TRAVEL and check for clashes).
3. **The stability check is optimistic.** It treats every printed part as 35 % solid, but the shells
   are 2.3 mm walls, which print solid. With wall-aware mass: 2.93 kg, centre of mass z = 152, the
   rear caster carries 12 %, and the minimum tip angle is 19.2°, which fails. `load_asm()` also picks
   up stale meshes (head_face, caster_spacer_front, _v_caster_F/R, _v_lidar_ld19) left over in
   out/assembly. The ballast has no mount.
   *Fix:*
   - mass = 1.24 × (min(V, A × 1.2) + 0.15 × the rest);
   - only load the current part names, and clean out/assembly before export;
   - add a ballast pocket or bolt (probably +100 g).
4. **The tilt clutch can't hold the head up.** Its Ø18 friction face at r ≈ 6 with one M3 and a
   wave washer needs about 55 N clamp to hold a realistic 400 g head at −15°.
   *Fix:*
   - move the friction face out to a larger flange (r ≈ 15) with a Belleville stack, or key the hub and rely on the 10 % torque limit;
   - the tilt adapter also needs the horn-screw relief that clutch_hub has.
5. **The hard-stop finger is too small.** It's 3 × 3 mm PETG on a 5.5 mm cantilever, and a child
   twisting the head puts about 400 N on it. *Fix:* make it ≥ 6 mm wide, and take the contact on the
   frame plate rather than the hub.
6. **Docs and code disagree:**
   - LED_COUNT is 12 in the firmware, but the ring is 16 LEDs;
   - DESIGN.md:355 still says "tilt over 25°";
   - config.h:51 says the tip angle is "~24 deg";
   - firmware tof.h, reflex.h and the README give the drop angles as ±42°/150°, but the CAD has ±27°/145°;
   - BOM line 32 says M2.5 for the tilt hub, but the CAD uses M3;
   - a USB-C overmold is 10–12.5 mm wide and won't pass the Ø10 hub bore, so widen the bore or use a soldered/flat cable.
7. **Smaller:**
   - The head's 5 V (3 × MG90S, the mic amp, the LCDs) shares the Pi's buck. Give it a separate 5 V
     supply or a polyfuse.
   - Clamp tilt while driving, so the head ToF stays level.
   - The camera hole gives 109° unvignetted, not 120° (fine, but update the docs).

Fixed and confirmed: B1, B4 (logic), S1 (mostly), S2, S4, S6, S7, S8 (adequate), S9, S10 and most of
the minor items.
