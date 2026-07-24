function pathWithSearchAndHash(value: URL): string {
  return `${value.pathname}${value.search}${value.hash}`;
}

/**
 * Keep local fixture/dev auth redirects on the browser's current origin even
 * when a shell-level AUTH_URL/NEXTAUTH_URL points at production.
 */
export function resolveAuthRedirectUrl({
  url,
  baseUrl,
  nodeEnv = process.env.NODE_ENV,
}: {
  url: string;
  baseUrl: string;
  nodeEnv?: string;
}): string {
  if (nodeEnv !== "production") {
    if (url.startsWith("/")) {
      return url;
    }

    try {
      const target = new URL(url);
      return pathWithSearchAndHash(target);
    } catch {
      return "/";
    }
  }

  if (url.startsWith("/")) {
    return `${baseUrl}${url}`;
  }

  try {
    const target = new URL(url);
    if (target.origin === baseUrl) {
      return url;
    }
  } catch {
    // Fall through to the safe app root.
  }

  return baseUrl;
}