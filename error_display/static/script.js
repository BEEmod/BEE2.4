
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

	// Lock the article to use multiples of the tile size.
	const update = () => {
		const screen_width = document.documentElement.clientWidth - PADDING;
		const screen_height = document.documentElement.clientHeight - PADDING;

		content_box.style.width = `${Math.floor(screen_width / TILE_SIZE) * TILE_SIZE}px`;
		content_box.style.height = `${Math.floor(screen_height / TILE_SIZE) * TILE_SIZE}px`;
	};
	window.visualViewport.addEventListener("resize", update);

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
	update();

	const scene = new THREE.Scene({background: 0xC9D3CF});  // PeTI BG.
	const camera = new THREE.PerspectiveCamera( 75, 1.0, 0.01, 100 );

	const mats = new Map();
	mats.set("white", new THREE.MeshBasicMaterial({color: 0xFFFFFF}));
	mats.set("black", new THREE.MeshBasicMaterial({color: 0x83878B}));
	mats.set("goo", new THREE.MeshBasicMaterial({color: 0x5C6D72}));
	mats.set("back", new THREE.MeshBasicMaterial({color: 0x777777}));

	const renderer = new THREE.WebGLRenderer();
	renderer.setSize( 512, 512 );

	const controls = new OrbitControls( camera, renderer.domElement );

	function updateScene(data) {
		console.log("Scene data:", data);

		const tile_geo = new THREE.BoxGeometry(0.5, 0.5, 0.5); //new THREE.PlaneGeometry(1.0, 1.0);

		// const orients = new Map({
		// 	n: new THREE.Quaternion().setFromAxisAngle(),
		// 	s: new THREE.Quaternion().setFromAxisAngle(),
		// 	e: new THREE.Quaternion().setFromAxisAngle(),
		// 	w: new THREE.Quaternion().setFromAxisAngle(),
		// 	t: new THREE.Quaternion().setFromAxisAngle(),
		// 	b: new THREE.Quaternion().setFromAxisAngle(new THREE.Vector(0, 1, 0), 180),
		// });

		for (const kind of ["white", "black", "goo", "back"]) {
			const tileList = data.tiles[kind];
			if (tileList === undefined) {
				continue;
			}
			// const mesh = new THREE.InstancedMesh(tile_geo, mats.get(kind), tileList.length);
			// const mat = new THREE.Matrix4();
			// const scale = new THREE.Vector3(1, 1, 1);
			// const rot = new THREE.Quaternion();
			for (let i = 0; i < tileList.length; i++) {
				const tile = tileList[i];
				// mesh.setMatrixAt(i, mat.compose(
				// 	new THREE.Vector3(tile.position[0], tile.position[1], tile.position[2]),
				// 	rot,
				// 	scale,
				// ));
				const mesh = new THREE.Mesh(tile_geo, mats.get(kind));
				mesh.position.set(tile.position[0], tile.position[2], -tile.position[1]);
				scene.add(mesh);
			}
			// mesh.instanceMatrix.needsUpdate = true;
			// scene.add(mesh);
		}

		const geometry = new THREE.BoxGeometry( 1, 1, 1 );
		const material = new THREE.MeshBasicMaterial( { color: 0x00ff00 } );
		const cube = new THREE.Mesh( geometry, material );
		scene.add( cube );

		camera.position.z = 5;
		controls.update();

		function animate() {
			requestAnimationFrame( animate );
			controls.update();
			renderer.render( scene, camera );
		}
		console.log("Constructed scene!", scene);
		document.querySelector("#render").appendChild(renderer.domElement);
		animate();
	}

	fetch("/displaydata")
		.then((data) => data.json())
		.then((json) => {updateScene(json)})
		.catch((reason) => {
			console.error(reason);
			content_box.append('Could not fetch display!');
	});
});
