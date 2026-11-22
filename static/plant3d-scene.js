// Low-poly Three.js scene for the plant view. Geometry only: every number shown
// comes from the API values passed in; nothing is computed here.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const BLUE = 0x2f80ed;
const ORANGE = 0xf08a24;
const HOME = [28, 20, 30]; // initial camera position
const TARGET = [-1, 2, -1];
const PARTICLES = 14;
const SPEED_UNITS = 9; // world units per second at the plant's maximum campus load
const FLOOR_H = 1.3;
const BLOCK_X = 13;
const TANK_H = 8;

// key -> [colour, points]; supply segments are blue, the warm return is orange.
const SEGMENTS = {
  sac_campus: [BLUE, [[-12, 1.2, -9.6], [-8, 1.2, -11], [8, 1.2, -11], [8, 1.2, -8]]],
  ec_tank: [BLUE, [[-15, 0.6, 6.7], [-15, 0.6, 5], [-6, 0.6, 5], [-3, 0.9, 2], [-2.9, 0.9, 0.5]]],
  ec_campus: [BLUE, [[-8, 0.6, 6.7], [-8, 0.6, 6.2], [6, 0.6, 6.2], [8, 1.2, 3]]],
  tank_campus: [BLUE, [[3, 1.2, 0], [8, 1.2, 0]]],
  // supply header along the blocks' west side; each block has its own stub ending on its west face (x = 10.5)
  campus_header: [BLUE, [[8, 1.2, -11], [8, 1.2, 7]]],
  to_academic: [BLUE, [[8, 1.2, -7], [10.5, 1.2, -7]]],
  to_evening: [BLUE, [[8, 1.2, 0], [10.5, 1.2, 0]]],
  to_base: [BLUE, [[8, 1.2, 7], [10.5, 1.2, 7]]],
  // warm return: starts on the last block's east face, collects behind the blocks, runs west along z = -13,
  // south along x = -19, then east along z = 10.5 and ends on the EC3 south face (z = 9.3)
  return: [ORANGE, [[15.5, 0.5, 7], [17, 0.5, 7], [17, 0.5, -13], [-19, 0.5, -13], [-19, 0.5, 10.5], [-5, 0.5, 10.5], [-5, 0.5, 9.3]]],
};
// thin static return branches (always shown): each one joins the trunk and ends on a component or block face
const STUBS = [
  [[15.5, 0.5, 0], [17, 0.5, 0]],
  [[15.5, 0.5, -7], [17, 0.5, -7]],
  [[-19, 0.5, -6], [-16.5, 0.5, -6]],
  [[-19, 0.5, -9.6], [-16.5, 0.5, -9.6]],
  ...[-16, -12.4, -8.8].map((x) => [[x, 0.5, 10.5], [x, 0.5, 9.3]]),
];
const ECS_X = [0, 1, 2, 3].map((i) => -16 + i * 3.6);
export const STUB_POINTS = Object.fromEntries(STUBS.map((p, i) => [`stub${i}`, p]));
export const BOXES = [
  { id: "sac0", min: [-16.5, 0, -7.5], max: [-11.5, 2.5, -4.5] },
  { id: "sac1", min: [-16.5, 0, -11.1], max: [-11.5, 2.5, -8.1] },
  ...ECS_X.map((x, i) => ({ id: `ec${i}`, min: [x - 1.3, 0, 6.7], max: [x + 1.3, 2, 9.3] })),
  { id: "tank", min: [-3, 0, -3], max: [3, TANK_H, 3] },
];
export const SEGMENT_POINTS = Object.fromEntries(Object.entries(SEGMENTS).map(([k, v]) => [k, v[1]]));
export const BLOCKS = [
  { key: "academic", z: -7, floors: 6 },
  { key: "evening", z: 0, floors: 4 },
  { key: "base", z: 7, floors: 3 },
];
for (const b of BLOCKS) {
  BOXES.push({ id: b.key, min: [BLOCK_X - 2.5, 0, b.z - 2.5], max: [BLOCK_X + 2.5, b.floors * FLOOR_H, b.z + 2.5] });
}

const curveOf = (pts) =>
  new THREE.CatmullRomCurve3(pts.map((p) => new THREE.Vector3(...p)), false, "catmullrom", 0);

export function createScene(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  container.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b1424);
  const camera = new THREE.PerspectiveCamera(40, 1.6, 0.1, 300);
  camera.position.set(...HOME);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(...TARGET);
  controls.enableDamping = false;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 12;
  controls.maxDistance = 90;
  controls.update();

  scene.add(new THREE.AmbientLight(0xffffff, 0.75));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(-20, 40, 30);
  scene.add(sun);

  const pickables = [];
  const mk = (geo, color, opts = {}, tip = null) => {
    const m = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ color, ...opts }));
    scene.add(m);
    if (tip) {
      m.userData.tip = tip;
      pickables.push(m);
    }
    return m;
  };
  const glass = { transparent: true, depthWrite: false, side: THREE.DoubleSide };

  const ground = mk(new THREE.PlaneGeometry(46, 32), 0x13203a);
  ground.rotation.x = -Math.PI / 2;

  [-6, -9.6].forEach((z) => {
    mk(new THREE.BoxGeometry(5, 2.5, 3), 0x16918b, {}, { id: "sac" }).position.set(-14, 1.25, z);
  });
  const ecs = [0, 1, 2, 3].map((i) => {
    const m = mk(new THREE.BoxGeometry(2.6, 2, 2.6), 0x7b8794, {}, { id: "ec", index: i });
    m.position.set(-16 + i * 3.6, 1, 8);
    return m;
  });

  mk(new THREE.CylinderGeometry(3, 3, TANK_H, 12, 1, true), 0x9fc3ff, { ...glass, opacity: 0.22 }, { id: "tank" })
    .position.set(0, TANK_H / 2, 0);
  const waterH = TANK_H - 0.4;
  const water = mk(new THREE.CylinderGeometry(2.8, 2.8, waterH, 12), BLUE, { transparent: true, opacity: 0.85 }, { id: "tank" });

  const anchors = {
    sac: new THREE.Vector3(-17, 3.2, -7.8),
    ec: new THREE.Vector3(-10, 3, 8),
    tank: new THREE.Vector3(2, TANK_H + 2.2, 0),
    campus: new THREE.Vector3(BLOCK_X, 0.2, 11),
  };
  for (const b of BLOCKS) {
    const h = b.floors * FLOOR_H;
    const body = mk(new THREE.BoxGeometry(5, h, 5), 0x8fa3c4, { ...glass, opacity: 0.12 }, { id: b.key });
    body.position.set(BLOCK_X, h / 2, b.z);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(body.geometry), new THREE.LineBasicMaterial({ color: 0xaab9d6 }));
    edges.position.copy(body.position);
    scene.add(edges);
    for (let f = 0; f <= b.floors; f++) {
      mk(new THREE.BoxGeometry(5, 0.12, 5), 0x8fa3c4, { transparent: true, opacity: 0.55 }, { id: b.key })
        .position.set(BLOCK_X, 0.06 + f * FLOOR_H, b.z);
    }
    anchors[b.key] = new THREE.Vector3(BLOCK_X, h + 0.5, b.z);
  }

  // static thin return branches
  for (const pts of STUBS) {
    mk(new THREE.TubeGeometry(curveOf(pts), 12, 0.12, 5, false), ORANGE, { transparent: true, opacity: 0.5 });
  }

  // flow segments: a tube (dim when idle) plus particles (only while RT > 0)
  const segs = {};
  const dot = new THREE.SphereGeometry(0.28, 6, 4);
  for (const [key, [color, pts]] of Object.entries(SEGMENTS)) {
    const curve = curveOf(pts);
    const tube = mk(new THREE.TubeGeometry(curve, 48, 0.3, 6, false), color, { transparent: true, opacity: 0.3 }, { id: "seg", key });
    const inst = new THREE.InstancedMesh(dot, new THREE.MeshBasicMaterial({ color: 0xffffff }), PARTICLES);
    inst.visible = false;
    inst.frustumCulled = false;
    scene.add(inst);
    segs[key] = { curve, tube, inst, phase: 0, rt: 0, len: curve.getLength() };
  }

  const tmp = new THREE.Object3D();
  const pt = new THREE.Vector3();
  const ray = new THREE.Raycaster();
  let maxLoad = 1;

  return {
    anchors,
    getCamera: () => camera.position.toArray(),
    setCamera(p) {
      camera.position.set(p[0], p[1], p[2]);
      controls.update();
    },
    resetView() {
      camera.position.set(...HOME);
      controls.target.set(...TARGET);
      controls.update();
    },
    resize(w, h) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    },
    // ecCount and frac come straight from the API row / plant (frac = tank_level_rth / tank_capacity_rth)
    update({ ecCount, frac, flows, max }) {
      maxLoad = Math.max(1, max);
      ecs.forEach((m, i) => m.material.color.setHex(i < ecCount ? 0xf2b73a : 0x7b8794));
      water.scale.y = Math.max(Math.min(1, Math.max(0, frac)), 0.001);
      water.position.set(0, 0.2 + (waterH * water.scale.y) / 2, 0);
      for (const [k, s] of Object.entries(segs)) {
        s.rt = flows[k] || 0;
        s.inst.visible = s.rt > 0;
        s.tube.material.opacity = s.rt > 0 ? 0.9 : 0.3;
      }
    },
    advance(dt) {
      for (const s of Object.values(segs)) {
        if (s.rt <= 0) continue;
        s.phase = (s.phase + (dt * SPEED_UNITS * (s.rt / maxLoad)) / s.len) % 1;
        for (let i = 0; i < PARTICLES; i++) {
          s.curve.getPointAt((s.phase + i / PARTICLES) % 1, pt);
          tmp.position.copy(pt);
          tmp.updateMatrix();
          s.inst.setMatrixAt(i, tmp.matrix);
        }
        s.inst.instanceMatrix.needsUpdate = true;
      }
    },
    render: () => renderer.render(scene, camera),
    project(id, w, h) {
      const v = anchors[id].clone().project(camera);
      return { x: (v.x * 0.5 + 0.5) * w, y: (-v.y * 0.5 + 0.5) * h, on: v.z < 1 };
    },
    pick(x, y) {
      ray.setFromCamera({ x, y }, camera);
      const hit = ray.intersectObjects(pickables, false)[0];
      return hit ? hit.object.userData.tip : null;
    },
  };
}
