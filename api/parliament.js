// Vercel serverless function — proxies Parliament Members API
// Deployed at: /api/parliament?path=/Members/Search?...
// Bypasses CORS since the request comes from the server, not the browser.

export default async function handler(req, res) {
  const path = req.query.path;

  if (!path) {
    return res.status(400).json({ error: 'Missing path parameter' });
  }

  const url = 'https://members-api.parliament.uk/api' + path;

  try {
    const response = await fetch(url, {
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Spectrm/1.0 (+https://onthespectrm.com)',
      },
    });

    if (!response.ok) {
      return res.status(response.status).json({ error: 'Parliament API error', status: response.status });
    }

    const data = await response.json();

    // Cache for 5 minutes on Vercel edge
    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    res.setHeader('Access-Control-Allow-Origin', '*');
    return res.status(200).json(data);

  } catch (err) {
    return res.status(500).json({ error: 'Proxy error', message: err.message });
  }
}
