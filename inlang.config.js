// filename: inlang.config.js

export async function defineConfig(env) {
  // importing a plugin
  const plugin = await env.$import(
    "https://cdn.jsdelivr.net/gh/jannesblobel/inlang-plugin-po@1/dist/index.js"
  );

  // most plugins require additional config, read the plugins documentation
  // for the required config and correct usage.
  const pluginConfig = {
    pathPattern: "./i18n/{language}.po",
    referenceResourcePath: "./i18n/BEE2.pot",
  };

  return {
    referenceLanguage: "BEE2",
    languages: ["es", "fr", "ja", "pl", "ru", "zh_cn"],
    readResources: (args) =>
      plugin.readResources({ ...args, ...env, pluginConfig }),
    writeResources: (args) =>
      plugin.writeResources({ ...args, ...env, pluginConfig }),
  };
}
