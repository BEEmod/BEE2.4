import * as THREE from './three.js';
import {OrbitControls} from "./OrbitControls.js";
import {OBJLoader} from "./OBJLoader.js";

window.addEventListener("load", () => {
	const TILE_SIZE = 64;
	const PADDING = 96;
	const FREQ = 30 * 1000;

	const fireHeartbeat = () => {
		navigator.sendBeacon("/heartbeat");
		console.log("Heartbeat!");
	};

	let heartbeatID = setInterval(fireHeartbeat, FREQ);

	// If the window is hidden (including when the Steam Overlay is closed!!), stop sending
	// heartbeat messages so the server can die.
	document.addEventListener("visibilitychange", () => {
		if (document.visibilityState === 'visible') {
			fireHeartbeat(); // Fire immediately, in case there was a long time from the last interval.
			if (heartbeatID === null) {
				heartbeatID = setInterval(fireHeartbeat, FREQ);
			}
		} else {
			if (heartbeatID !== null) {
				clearInterval(heartbeatID);
				heartbeatID = null;
			}
		}
	});

	const scene = new THREE.Scene();
	const container = document.querySelector("#render");
	scene.background = new THREE.Color(0xC9D3CF);  // PeTI BG.
	const camera = new THREE.PerspectiveCamera( 75, 1.0, 0.01, 100 );
	const renderer = new THREE.WebGLRenderer();
	const controls = new OrbitControls( camera, renderer.domElement );

	function convertAngle(pitch, yaw, roll) {
		return new THREE.Euler(
			pitch * Math.PI / 180,
			(yaw + 90.0) * Math.PI / 180,
			roll * Math.PI / 180,
			"YZX",
		);
	}

	async function updateScene(data) {
		const mats = new Map();
		const loader_tex = new THREE.TextureLoader();
		async function load_tex_wrapping(filename) {
			// Textures don't wrap by default.
			const tex = await loader_tex.loadAsync(filename);
			tex.wrapS = THREE.RepeatWrapping;
			tex.wrapT = THREE.RepeatWrapping;
			return tex;
		}
		const loader_obj = new OBJLoader();
		mats.set("white", new THREE.MeshToonMaterial({
			map: await load_tex_wrapping('static/grid3.png'),
		}));
		mats.set("black", new THREE.MeshToonMaterial({
			map: await load_tex_wrapping('static/grid3b.png'),
		}));
		mats.set("goopartial", new THREE.MeshToonMaterial({
			map: await load_tex_wrapping('static/grid_goo_partial.png'),
		}));
		mats.set("goofull", new THREE.MeshToonMaterial({
			map: await load_tex_wrapping('static/grid_goo_full.png'),
}		));
		mats.set("glass", new THREE.MeshToonMaterial({
			color: 0x3CA1ED,
			transparent: true,
			opacity: 0.33,
			side: THREE.DoubleSide,
		}));
		mats.set("grating", new THREE.MeshToonMaterial({
			map: await load_tex_wrapping('static/grating.png'),
			transparent: true,
			side: THREE.DoubleSide,
		}));
		mats.set("goo", new THREE.MeshToonMaterial({
			color: 0x5C6D72,
			transparent: true,
			opacity: 0.8,
		}));
		mats.set("back", new THREE.MeshToonMaterial({color: 0x777777}));

		const white_mats = [null, null, null];
		const black_mats = [null, null, null];
		for (let i = 0; i < 3; i++) {
			white_mats[i] = new THREE.MeshToonMaterial({
				map: await loader_tex.loadAsync(`static/grid${i}.png`),
			});
			black_mats[i] = new THREE.MeshToonMaterial({
				map: await loader_tex.loadAsync(`static/grid${i}b.png`),
			});
		}

		const select_mat = new THREE.MeshToonMaterial({
			color: 0xFAFA28, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
		});
		const pointfile_mat = new THREE.LineBasicMaterial({color: 0xFF0000});
		const lines_mat = new THREE.LineBasicMaterial({color: 0x00FFFF});

		scene.add( new THREE.AmbientLight( 0x888888 ) );
		const lighting = new THREE.DirectionalLight( 0xffffff, 0.5 );
		scene.add(lighting);
		lighting.position.set(-20, 50, 20);
		lighting.target.position.set(5, 0, 5);
		scene.add(lighting.target);
		console.log("Scene data:", data);

		const rect_geo = new Map();
		const orients = new Map();
		orients.set("n", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI));
		orients.set("s", new THREE.Quaternion());
		orients.set("e", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2));
		orients.set("w", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 3 * Math.PI / 2));
		orients.set("u", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2.0));
		orients.set("d", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), +Math.PI / 2.0));

		const axes = new Map();
		axes.set("x", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI / 2));
		axes.set("y", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI / 2));
		axes.set("z", new THREE.Quaternion());

		for (const kind of ["white", "black", "goo", "goopartial", "goofull", "back", "glass", "grating"]) {
			const tileList = data.tiles[kind];
			if (tileList === undefined) {
				continue;
			}
			// TODO: Maybe use this for efficiency?
			// const mesh = new THREE.InstancedMesh(tile_geo, mats.get(kind), tileList.length);
			// const matrix = new THREE.Matrix4();
			// const scale = new THREE.Vector3(1, 1, 1);
			for (let i = 0; i < tileList.length; i++) {
				const tile = tileList[i];
				// mesh.setMatrixAt(i, matrix.compose(
				// 	new THREE.Vector3(tile.position[0], tile.position[1], tile.position[2]),
				// 	rot,
				// 	scale,
				// ));
				let mat;
				if ((kind === "black" || kind === "white") && tile.orient !== "u" && tile.orient !== "d") {
					mat = (kind === "white" ? white_mats : black_mats)[Math.floor(Math.random() * 3)];
				} else {
					mat = mats.get(kind);
				}

				let geo = rect_geo.get({width: tile.width, height: tile.height})
				if (geo === undefined) {
					// Can't use PlaneGeometry because we need to resize the UVs.
					// Data here copied from that.
					// geo = new THREE.PlaneGeometry(2, 4);
					geo = new THREE.BufferGeometry();
					geo.setIndex([0, 2, 1, 2, 3, 1]);
					geo.setAttribute("position", new THREE.Float32BufferAttribute([
						-tile.width/2, tile.height/2, 0,
						tile.width/2, tile.height/2, 0,
						-tile.width/2, -tile.height/2, 0,
						tile.width/2, -tile.height/2, 0,
					], 3));
					geo.setAttribute("normal", new THREE.Float32BufferAttribute([
						0, 0, 1,
						0, 0, 1,
						0, 0, 1,
						0, 0, 1,
					], 3));
					geo.setAttribute("uv", new THREE.Float32BufferAttribute([
						0, tile.height,
						tile.width, tile.height,
						0, 0,
						tile.width, 0,
					], 2))
					rect_geo.set({width: tile.width, height: tile.height}, geo);

				}
				const mesh = new THREE.Mesh(geo, mat);
				mesh.position.set(tile.position[0], tile.position[2], -tile.position[1]);
				mesh.applyQuaternion(orients.get(tile.orient));
				scene.add(mesh);
			}
			// mesh.instanceMatrix.needsUpdate = true;
			// scene.add(mesh);
		}

		const voxels_geo = new THREE.BoxGeometry(0.5, 0.5, 0.5);
		for (const voxels of data.voxels) {
			const mesh = new THREE.Mesh(voxels_geo, select_mat);
			mesh.position.set(voxels[0], voxels[1], voxels[2]);
			scene.add(mesh);
		}

		const points_geo = new THREE.SphereGeometry(12.0/128.0, 16, 16);
		for (const points of data.points) {
			const mesh = new THREE.Mesh(points_geo, select_mat);
			mesh.position.set(points[0], points[1], points[2]);
			scene.add(mesh);
		}

		if (data.leak) {
			const geo = new THREE.BufferGeometry().setFromPoints(data.leak.map(
				point => new THREE.Vector3(point[0], point[1], point[2])
			));
			scene.add(new THREE.Line(geo, pointfile_mat));
		}

		if (data.lines) {
			const geo = new THREE.BufferGeometry().setFromPoints(data.lines.flatMap(
				pair => [
					new THREE.Vector3(pair[0][0], pair[0][1], pair[0][2]),
					new THREE.Vector3(pair[1][0], pair[1][1], pair[1][2]),
				]
			));
			scene.add(new THREE.LineSegments(geo, lines_mat));
		}

		if (data.barrier_holes.length > 0) {
			await loader_obj.loadAsync('static/barrier_hole.obj').then((hole_geo) => {
				console.log("Hole: ", hole_geo);
				const hole_mats = new Map();
				hole_mats.set("selection", select_mat);
				hole_mats.set("framing", new THREE.MeshToonMaterial({color: 0xCCCCCC}));
				for (const hole of data.barrier_holes) {
					for (const child of hole_geo.children) {
						// shape = small/medium/large etc, kind = frame/footprint
						// The shape is something like medium_frame, slot_center_footprint
						// Data is {footprint: bool, shape: str}.
						const underscore_pos = child.name.lastIndexOf("_");
						if (underscore_pos === -1) { continue; }
						const shape = child.name.slice(0, underscore_pos);
						const kind = child.name.slice(underscore_pos + 1);
						if (hole.shape === shape && (kind === "frame" || hole.footprint)) {
							const mesh = new THREE.Mesh(child.geometry, hole_mats.get(child.material.name));
							mesh.position.set(hole.pos[0], hole.pos[1], hole.pos[2]);
							mesh.setRotationFromEuler(convertAngle(hole.pitch, hole.yaw, hole.roll));
							scene.add(mesh);
						}
					}
				}
			});
		}

		camera.position.set(-5, 3, 5);
		controls.update();

		console.log("Constructed scene!", scene);
		container.appendChild(renderer.domElement);

		// No animations, no need to render every frame.
		controls.addEventListener('change', () => renderer.render(scene, camera));
		setTimeout(() => renderer.render(scene, camera), 150);
	}

	fetch("/displaydata")
		.then((data) => data.json())
		.then(updateScene)
		.catch((reason) => {
			console.error(reason);
			container.innerText = 'Could not fetch display: ' + reason;
	});

	const update = () => {
		const screen_width = document.documentElement.clientWidth - PADDING;
		const screen_height = document.documentElement.clientHeight - PADDING;
		let height = Math.floor(screen_height / TILE_SIZE);
		if (height > 8) {
			height = 8;
		}
		height *= TILE_SIZE;

		container.style.width = `${Math.floor(screen_width / TILE_SIZE) * TILE_SIZE}px`;
		container.style.height = `${height}px`;

		const render_bbox = container.getBoundingClientRect();
		camera.aspect = render_bbox.width / height;
		camera.updateProjectionMatrix();
		renderer.setSize( render_bbox.width, height );
		renderer.render(scene, camera);
	};
	window.visualViewport.addEventListener("resize", update);
	update();

	const render_details = document.getElementById("render-details");
	render_details.addEventListener("toggle", () => {
		if (render_details.open) {
			update();
		}
	})
});
