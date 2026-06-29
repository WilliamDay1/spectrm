// Vercel serverless function — proxies Commons Votes API
// Deployed at: /api/votes?path=/data/divisions.json/membervoting?memberId=...

export default async function handler(req, res) {
  const path = req.query.path;

  if (!path) {
    return res.status(400).json({ error: 'Missing path parameter' });
  }

  const url = 'https://commonsvotes-api.parliament.uk' + path;

  try {
    const response = await fetch(url, {
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Spectrm/1.0 (+https://onthespectrm.com)',
      },
    });

    if (!response.ok) {
      return res.status(response.status).json({ error: 'Votes API error', status: response.status });
    }

    const data = await response.json();

    res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=600');
    res.setHeader('Access-Control-Allow-Origin', '*');
    return res.status(200).json(data);

  } catch (err) {
    return res.status(500).json({ error: 'Proxy error', message: err.message });
  }
}
