import { AssistantPage } from './components/AssistantPage';
import { SimulatorPage } from './components/SimulatorPage';

export default function App() {
  return window.location.pathname.startsWith('/simulator') ? <SimulatorPage /> : <AssistantPage />;
}
