/* Vite resolves these imports to a hashed URL under dist/assets, which is the
 * one directory twin_api mounts -- so an image imported this way is served in
 * production without adding another static mount. */
declare module "*.jpg" {
  const src: string;
  export default src;
}
declare module "*.png" {
  const src: string;
  export default src;
}
declare module "*.svg" {
  const src: string;
  export default src;
}
