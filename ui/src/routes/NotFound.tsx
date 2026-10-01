import { Link } from 'react-router';

export function NotFound() {
  return (
    <>
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the catalog</Link>
      </p>
    </>
  );
}
