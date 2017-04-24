# Academic URL Titles

`AcademicUrlTitles` is a
[Limnoria](https://github.com/ProgVal/Limnoria)/[Supybot](https://github.com/Supybot/Supybot)
plugin for pulling URLs pasted into IRC channels and displaying information
about the page/content.

This plugin is oriented around academic settings where commonly posted links
will include PDFs, videos and datasets. Since this plugin was originally
written to run in `##machinelearning` on [FreeNode](https://freenode.net/), it
includes integrations for [arXiv](https://arxiv.org).

This plugin is forked from [Detroll](https://github.com/jtatum/Detroll).
Improvements include SSL support (with optional fallback with warnings about
bad certs), replacing faulty `urllib2`, PDF title parsing, better URL extraction,
arXiv integration, and numerous stability and readability improvements.

## Installation

Installation is simple: clone this repo to your bot's plugins directory:

    cd bot-directory/plugins
    git clone https://github.com/brandonrobertz/AcademicUrlTitles

Then restart your bot or load it over IRC:

    <brand0>: @load AcademicUrlTitles
    <AcademicTitles>: The operation succeeded.

## Examples

Here's the bot in action:

    <brand0> https://arxiv.org/pdf/1507.02672.pdf
    <AcademicTitles> [ [1507.02672] Semi-Supervised Learning with Ladder Networks ]

    <brand0> http://journalism.stanford.edu/cj2016/files/What%20do%20journalists%20do%20with%20documents.pdf
    <AcademicTitles> [ What do journalists do with documents 7 (application/pdf, 5 pages) 211.0KB ]

    <brand0> https://expired.badssl.com/
    <AcademicTitles> [ (WARNING: BAD CERT) expired.badssl.com ]

    <brand0> https://www.youtube.com/watch?v=RvgYvHyT15E
    <AcademicTitles> [ NIPS 2016 Workshop on Adversarial Training - Ian Goodfellow - Introduction to GANs - YouTube ]

The bot will show you if the link was redirected, and what domain it was
redirected to:

    <brand0> http://www.facebook.com
    <AcademicTitles> [ (R: HTTPS) Facebook - Log In or Sign Up ]

    <brand0> https://developer.facebook.com
    <AcademicTitles> [ (R: developers.facebook.com) Facebook for Developers ]

If the server returns an unusual status code, the bot shows that too:

    <brand0> https://arxiv.org/sfdkjs09r8we
    <AcademicTitles> [ (404) Not found ]

This plugin requires the following Python modules:

- [PyPDF2](https://github.com/mstamy2/PyPDF2)
- [requests](http://docs.python-requests.org/en/master/)
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/)*
- [lxml](http://lxml.de/) (optional - improves parsing of title attribute)

* Avoid BeautifulSoup version 3.1 as it has serious problems
dealing with pages that contain some common JavaScript. If your Linux
distribution includes the 3.1 version of BeautifulSoup, remove it and use
easy_install to install 3.2 or newer.
