import argparse
import json
from pathlib import Path
from swarmforge import __version__
from swarmforge.core.simulator import Simulation,build_manifest
from swarmforge.core.trace import canonical,semantic_digest
from swarmforge.domain.model import InvalidScenario


def main():
    parser=argparse.ArgumentParser(description="SwarmForge simulation-only research core")
    sub=parser.add_subparsers(dest="cmd",required=True)
    run=sub.add_parser("run")
    run.add_argument("scenario",type=Path)
    run.add_argument("--algorithm",choices=["centralized_greedy","local_auction","scoped_lease"],default="centralized_greedy")
    run.add_argument("--seed",type=int,default=0)
    run.add_argument("--engine-version",default=__version__)
    run.add_argument("--output",type=Path,required=True)
    replay=sub.add_parser("replay")
    replay.add_argument("result",type=Path)
    replay.add_argument("--engine-version",default=__version__)
    bench=sub.add_parser("benchmark")
    bench.add_argument("--suite",choices=["smoke","research"],default="smoke")
    bench.add_argument("--output",type=Path,required=True)
    bench.add_argument("--contracts",type=Path,default=Path("contracts"))
    bench.add_argument("--engine-version",default=__version__)
    args=parser.parse_args()
    try:
        if args.cmd=="benchmark":
            from swarmforge.benchmark.runner import run_suite
            report=run_suite(args.suite,args.output,args.contracts,args.engine_version)
            if report["failed"]:
                parser.exit(1,"Benchmark includes failed runs; evidence preserved.\n")
        elif args.cmd=="run":
            config=json.loads(args.scenario.read_text())
            result=Simulation(build_manifest(config,args.seed,args.engine_version,algorithm=args.algorithm)).run()
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_bytes(canonical(result)+b"\n")
            print(json.dumps(result["metrics"],indent=2))
        else:
            original=json.loads(args.result.read_text())
            if original["manifest"]["engine_version"]!=args.engine_version:
                parser.error("engine version mismatch")
            if original["manifest"]["mode"]!="scripted":parser.error("interactive runs support event-log playback, not scripted replay")
            actual=Simulation(original["manifest"]).run()
            expected=original["metrics"]["trace_hash"]
            if expected!=semantic_digest(original["events"]) or expected!=actual["metrics"]["trace_hash"] or original["metrics"]!=actual["metrics"]:
                parser.error("replay mismatch")
            print("Replay verified:",expected)
    except (InvalidScenario,ValueError,KeyError,NotImplementedError,OSError) as exc:
        parser.error(str(exc))


if __name__=="__main__":
    main()
