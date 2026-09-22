import requests


def get_content_type(url):
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=15
        )

        content_type = response.headers.get("Content-Type")

        return {
            "url": response.url,
            "status_code": response.status_code,
            "content_type": content_type
        }

    except requests.RequestException as e:
        return {
            "url": url,
            "error": str(e)
        }


url = "https://www.thehindu.com/news/cities/bangalore/why-living-in-bengaluru-is-expensive-despite-namma-metro-as-compared-to-chennai-delhi-kolkata-mumbai/article71475382.ece"
result = get_content_type(url)

print(result)