"""Drivers behind small interfaces, so the agent doesn't care whether it's
talking to real hardware or the simulator.

    base.py        BaseLink    base ESP32 (wheels, neck, chest light, sensors)
    face.py        FaceLink    head ESP32 (eyes, ears, visor, touch pad)
    camera.py      Camera      USB camera, gated on the visor being open
    nav.py         Nav         go_to / approach / dock / turn_to / cancel
    voice.py       Voice       wake word + listening + speaking
    perception.py  Perception  who is visible
"""
