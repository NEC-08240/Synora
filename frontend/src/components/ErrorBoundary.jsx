import { Component } from 'react';
import { btn, card } from './Shell.jsx';
import { boundaryState } from '../uiState.js';

/** Catches render errors below it so a crash shows a message and a reload button instead of a blank screen. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = boundaryState.ok;
  }

  static getDerivedStateFromError() {
    return boundaryState.crashed;
  }

  componentDidCatch(error, info) {
    console.error('UI render error', error, info?.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div role="alert" className={`${card} max-w-sm space-y-4 text-center`}>
          <h1 className="text-xl font-bold">Something went wrong</h1>
          <p className="text-sm text-muted">The page could not be displayed. Try again, or reload if it keeps happening.</p>
          <div className="flex justify-center gap-3">
            <button onClick={() => this.setState(boundaryState.ok)} className={btn}>Try again</button>
            <button onClick={() => window.location.reload()} className={btn}>Reload</button>
          </div>
        </div>
      </div>
    );
  }
}
