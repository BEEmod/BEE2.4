// The actual common logic.
use std::env;
use std::fs;
use std::process;

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
                script: String::from(conf.get(sep + 1..).unwrap())
            }
        },
        None => Config::Frozen(conf),
    }
}

pub fn run_compiler(comp_name: &str) {
    println!("BEE compiler hook for {} started.", comp_name);

    // Grab the config left by the app.
    let conf = parse_config(fs::read_to_string("bee2/app_loc.paths").expect("No BEE config file."));
    println!("Config: {:?}", conf);
    let mut cmd;
    match conf {
        Config::Frozen(exe) => {
            cmd = process::Command::new(exe);
        }
        Config::PySource { exe, script } => {
            cmd = process::Command::new(exe);
            cmd.arg(script);
        }
    };
    // Add on the compiler to use.
    cmd.arg(comp_name);
    // Remove ourselves from the args list.
    cmd.args(env::args().skip(1));
    println!("Spawning compiler: {:?}", cmd);
    let result = cmd
        .spawn().expect("Could not start compiler.")
        .wait().expect("Could not wait for compiler.");
    process::exit(match result.code() {
        Some(code) => code,
        None => {
            eprintln!("Terminated by signal.");
            1
        }
    });
}
