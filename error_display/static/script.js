window.addEventListener("load", () => {
	const TILE_SIZE = 64;
	const PADDING = 96;
	const article = document.querySelector("article");
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

		article.style.width = `${Math.floor(screen_width / TILE_SIZE) * TILE_SIZE}px`;
		article.style.height = `${Math.floor(screen_height / TILE_SIZE) * TILE_SIZE}px`;
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
});
