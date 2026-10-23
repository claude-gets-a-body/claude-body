"""Build a BodyAgent from the config: picks the real or simulated driver for each part."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from common.clock import Clock

from .agent import BodyAgent
from .config import BodyConfig
from .drivers.base import BaseLink, SerialBaseLink, SimBaseLink
from .drivers.camera import FolderCamera, OpenCVCamera
from .drivers.face import FaceLink, SerialFaceLink, SimFaceLink
from .drivers.nav import Ros2NavAdapter, SimNav
from .drivers.perception import LidarPerception, SimPerception
from .drivers.voice import ConsoleVoice, LocalVoice
from .motion import MotionGuard, head_zone
from .safety import Safety

log = logging.getLogger(__name__)


@dataclass
class Body:
    agent: BodyAgent
    base: BaseLink
    face: FaceLink

    async def run(self) -> None:
        """Run the serial links (if any) and the agent together."""
        import asyncio
        await asyncio.gather(self.base.run(), self.face.run(), self.agent.run())


def build(cfg: BodyConfig, clock: Clock, out=print, agent_class=BodyAgent) -> Body:
    if cfg.base_driver == "serial":
        base = SerialBaseLink(cfg.base_port, cfg.baud)
    else:
        base = SimBaseLink()

    if cfg.face_driver == "serial":
        face = SerialFaceLink(cfg.face_port, cfg.baud)
    else:
        face = SimFaceLink()

    def visor_is_open() -> bool:
        return face.visor_state == "open"

    if cfg.camera_driver == "opencv":
        camera = OpenCVCamera(visor_is_open, cfg.camera_index, cfg.camera_max_px, cfg.jpeg_quality)
    else:
        camera = FolderCamera(visor_is_open, cfg.sim_frames_dir)

    motion = MotionGuard(base, cfg.v_max, cfg.w_max, cfg.a_max, cfg.heartbeat_hz)
    motion.head_zone = head_zone(face.head_mm)     # -1 (slow) on hardware until the face reports
    if cfg.nav_driver == "ros2":
        nav = Ros2NavAdapter(motion)
    else:
        distances = {name: p.sim_distance_m for name, p in cfg.places.items()}
        def dock_contacts(docked: bool) -> None:
            if isinstance(base, SimBaseLink):
                base.state["on_dock"] = base.state["charging"] = docked

        nav = SimNav(motion, distances, cfg.sim_time_scale, approach_speed=cfg.v_near_people, say=out,
                     on_dock_changed=dock_contacts)

    perception = LidarPerception() if cfg.nav_driver == "ros2" else SimPerception()
    voice = LocalVoice() if cfg.voice_driver == "local" else ConsoleVoice(out=out)
    agent = agent_class(cfg, base, face, camera, nav, voice, perception, motion, Safety(cfg, clock))
    return Body(agent=agent, base=base, face=face)
