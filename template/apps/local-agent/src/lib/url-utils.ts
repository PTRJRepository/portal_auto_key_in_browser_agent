export function normalizeStartUrl(rawUrl: string): string {
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    throw new Error("URL tidak boleh kosong.");
  }

  const withProtocol = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;

  try {
    const parsed = new URL(withProtocol);
    return parsed.toString();
  } catch {
    throw new Error(
      `URL tidak valid: "${rawUrl}". Gunakan format seperti https://example.com atau example.com`
    );
  }
}

