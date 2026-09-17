import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

/**
 * Последний рубеж: ошибка в любом компоненте не должна оставлять белую страницу.
 *
 * React снимает всё дерево, если исключение никто не поймал, и посетитель видит пустой экран
 * без единой подсказки. Здесь вместо этого показывается понятный экран с кнопкой перезагрузки
 * и раскрывающимся текстом ошибки - по нему видно, что чинить.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Сбой интерфейса:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <main className="page page--narrow">
        <div className="notice notice--error" role="alert">
          <h1>Страница не отрисовалась</h1>
          <p>Это сбой интерфейса, а не ваших данных. Перезагрузка почти всегда помогает.</p>
          <p className="crash__actions">
            <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
              Перезагрузить страницу
            </button>{" "}
            <a href="/">Вернуться к поиску</a>
          </p>
          <details className="crash__details">
            <summary>Подробности ошибки</summary>
            <pre>{error.message}</pre>
          </details>
        </div>
      </main>
    );
  }
}
