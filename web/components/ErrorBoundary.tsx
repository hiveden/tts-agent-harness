"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-neutral-50 dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 p-8">
          <div className="max-w-md text-center">
            <div className="text-red-500 dark:text-red-400 text-lg font-semibold mb-2">
              出错了
            </div>
            <div className="text-sm text-neutral-600 dark:text-neutral-400 font-mono break-all mb-4">
              {this.state.error.message || String(this.state.error)}
            </div>
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="px-4 py-2 text-sm rounded border border-neutral-300 dark:border-neutral-600 hover:bg-neutral-100 dark:hover:bg-neutral-800"
            >
              重试
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
