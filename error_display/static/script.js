window.addEventListener("load", () => {
	const TILE_SIZE = 128;
	const PADDING = 96;
	const article = document.querySelector("article");

	// Lock the article to use multiples of the tile size.
	const update = () => {
		const screen_width = document.documentElement.clientWidth - PADDING;
		const screen_height = document.documentElement.clientHeight - PADDING;

		article.style.width = `${Math.floor(screen_width / TILE_SIZE) * TILE_SIZE}px`;
		article.style.height = `${Math.floor(screen_height / TILE_SIZE) * TILE_SIZE}px`;
	};
	window.visualViewport.addEventListener("resize", update);
	update();
});
