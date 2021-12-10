// On Windows, apply the BEE2 icon.
extern crate winres;

fn main() {
  if cfg!(target_os = "windows") {
    let mut res = winres::WindowsResource::new();
    res.set_icon("../BEE2.ico");
    res.compile().unwrap();
  }
}
