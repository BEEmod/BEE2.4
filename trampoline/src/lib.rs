// The actual common logic.
use std::env;
use std::fs;

#[derive(Debug)]
enum Config {
    Frozen(String),
    PySource { exe: String, script: String },
}

fn parse_config(conf: String) -> Config {
    match conf.chars().position(|x| x == '\n') {
        Some(sep) => {
            Config::PySource {
                exe: String::from(conf.get(..sep).unwrap()),
                script: String::from(conf.get(sep+1..).unwrap())
            }
        },
        None => Config::Frozen(conf),
    }
}

pub fn run_compiler(comp_name: &str) {
    println!("BEE compiler hook for {} started.", comp_name);
    let p2_args: Vec<String> = env::args().collect();

    // Grab the config left by the app.
    let conf = parse_config(fs::read_to_string("bee2/app_loc.cfg").expect("No BEE config file."));
    println!("Config: {:?}", conf)
}
