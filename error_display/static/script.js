import * as THREE from './three.js';
import {OrbitControls} from "./OrbitControls.js";

window.addEventListener("load", () => {
	const TILE_SIZE = 64;
	const PADDING = 96;
	const content_box = document.querySelector("main");
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

	async function updateScene(data) {
		const mats = new Map();
		const loader_tex = new THREE.TextureLoader();
		mats.set("white", new THREE.MeshToonMaterial({
			map: await loader_tex.loadAsync('static/grid3.png'),
		}));
		mats.set("black", new THREE.MeshToonMaterial({
			map: await loader_tex.loadAsync('static/grid3b.png'),
		}));
		mats.set("goopartial", new THREE.MeshToonMaterial({
			map: await loader_tex.loadAsync('static/grid_goo_partial.png'),
		}));
		mats.set("goofull", new THREE.MeshToonMaterial({
			map: await loader_tex.loadAsync('static/grid_goo_full.png'),
}		));
		mats.set("glass", new THREE.MeshToonMaterial({
			color: 0x3CA1ED,
			transparent: true,
			opacity: 0.33,
			side: THREE.DoubleSide,
		}));
		mats.set("grating", new THREE.MeshToonMaterial({
			map: await loader_tex.loadAsync('static/grating.png'),
			transparent: true,
			side: THREE.DoubleSide,
		}));
		mats.set("goo", new THREE.MeshToonMaterial({
			color: 0x5C6D72,
			transparent: true,
			opacity: 0.8,
		}));
		mats.set("back", new THREE.MeshToonMaterial({color: 0x777777}));

		const white_mats = [0, 1, 2].map((i) =>
			new THREE.MeshToonMaterial({map: loader_tex.load(`static/grid${i}.png`)})
		);
		const black_mats = [0, 1, 2].map((i) =>
			new THREE.MeshToonMaterial({map: loader_tex.load(`static/grid${i}b.png`)})
		);

		const select_mat = new THREE.MeshToonMaterial({
			color: 0xFAFA28, transparent: true, opacity: 0.5, side: THREE.DoubleSide,
		});
		const pointfile_mat = new THREE.LineBasicMaterial({color: 0xFF0000});

		scene.add( new THREE.AmbientLight( 0x888888 ) );
		const lighting = new THREE.DirectionalLight( 0xffffff, 0.5 );
		scene.add(lighting);
		lighting.position.set(-20, 50, 20);
		lighting.target.position.set(5, 0, 5);
		scene.add(lighting.target);
		console.log("Scene data:", data);

		const tile_geo = new THREE.PlaneGeometry(1.0, 1.0);
		const grate_geo = new THREE.PlaneGeometry(1.0, 1.0);
		const orients = new Map();
		orients.set("n", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI));
		orients.set("s", new THREE.Quaternion());
		orients.set("e", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2));
		orients.set("w", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), 3 * Math.PI / 2));
		orients.set("u", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2.0));
		orients.set("d", new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), +Math.PI / 2.0));

		for (const kind of ["white", "black", "goo", "goopartial", "goofull", "back", "glass", "grating"]) {
			const tileList = data.tiles[kind];
			if (tileList === undefined) {
				continue;
			}
			// TODO: Maybe use this for efficiency?
			// const mesh = new THREE.InstancedMesh(tile_geo, mats.get(kind), tileList.length);
			// const mat = new THREE.Matrix4();
			// const scale = new THREE.Vector3(1, 1, 1);
			for (let i = 0; i < tileList.length; i++) {
				const tile = tileList[i];
				// mesh.setMatrixAt(i, mat.compose(
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
				const mesh = new THREE.Mesh(kind === "grating" ? grate_geo : tile_geo, mat);
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

		if (data.leak) {
			const geo = new THREE.BufferGeometry().setFromPoints(data.leak.map(
				point => new THREE.Vector3(point[0], point[1], point[2])
			));
			scene.add(new THREE.Line(geo, pointfile_mat));
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
			content_box.innerText = 'Could not fetch display: ' + reason;
	});

	// Lock the article to use multiples of the tile size.
	const update = () => {
		const screen_width = document.documentElement.clientWidth - PADDING;
		const screen_height = document.documentElement.clientHeight - PADDING;
		const box_height = Math.floor(screen_height / TILE_SIZE) * TILE_SIZE;

		content_box.style.width = `${Math.floor(screen_width / TILE_SIZE) * TILE_SIZE}px`;
		content_box.style.height = `${box_height}px`;

		const render_bbox = container.getBoundingClientRect();
		const height = box_height - render_bbox.y + 16;
		camera.aspect = render_bbox.width / height;
		camera.updateProjectionMatrix();
		renderer.setSize( render_bbox.width, height );
		renderer.render(scene, camera);
	};
	window.visualViewport.addEventListener("resize", update);
	update();
});
