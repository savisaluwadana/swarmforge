import "./globals.css";
import {Shell} from "../components/shell";
export const metadata={title:"SwarmForge | Fleet resilience laboratory",description:"Simulation-first reliability experiments for autonomous robotic fleets."};
export default function Layout({children}){return <html lang="en"><body><Shell>{children}</Shell></body></html>}
