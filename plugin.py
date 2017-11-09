###
# Copyright (c) 2017, Brandon Roberts <brandon@bxroberts.org>
# Copyright (c) 2012, James Tatum
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import re
import urlparse
import requests
import urllib3
import ssl

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
import supybot.conf as conf

from cookielib import CookieJar
from BeautifulSoup import BeautifulSoup
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
from urllib3.contrib import pyopenssl

from pdftitle import pdf2information
import pafy


try:
    import lxml.html
except ImportError:
    pass


# workaround for Python 2.7.9 (SNI)
class MyAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize,
            ssl_version=ssl.PROTOCOL_TLSv1, block=block)

# don't print SSL warnings into logs every time we do a lookup
pyopenssl.inject_into_urllib3()
urllib3.disable_warnings()

# Control characters to skip from HTML prints
CONTROL_CHARS = dict.fromkeys(range(32))
# User agent of the bot
USERAGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' \
    '(KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'
# Encoding for IRC output
ENCODING = 'utf8'
# ignore all messages from these nicks (or partial matches) all lowercased
IGNORES = [
    'ml-feeds', 'ml-helper', 'nutrofeeds'
]
MAX_RETRIES = 2


class AcademicUrlTitles(callbacks.Plugin):
    """
    When loaded, this plugin will display information about URLs pasted by
    users. This is optimized for academic settings where commonly posted links
    include PDFs and datasets. Includes integration for j.mp and arXiv.
    """
    threaded = True
    cj = CookieJar()
    ARXIV_RE = 'https?://arxiv.org/pdf/([0-9\.v]+)\.pdf'

    def clean(self, msg):
        """
        Clean a url's title or a message in general
        """
        cleaned = msg.translate(CONTROL_CHARS).strip()
        return re.sub(r'\s+', ' ', cleaned)

    def doPrivmsg(self, irc, msg):
        """
        Entry point for our bot. This gets hit every time a message arrives
        in a channel we are in or a PM.
        """
        if not msg.nick:
            return "skipping message from blank nick"

        for nick in IGNORES:
            if nick in msg.nick.lower():
                print "skipping msg from {}. Matched IGNORES list {}".format(
                    msg.nick.lower(), nick
                )
                return

        if ircmsgs.isCtcp(msg) and not ircmsgs.isAction(msg):
            return

        channel = msg.args[0]
        if irc.isChannel(channel):
            if ircmsgs.isAction(msg):
                text = ircmsgs.unAction(msg)
            else:
                text = msg.args[1]
            for url in utils.web.urlRe.findall(text):
                title = self.get_url_title(url)
                if title:
                    irc.queueMsg(ircmsgs.privmsg(channel, title))

    def get_url_title(self, url):
        """
        Handle everything required for fetching and parsing URL information into
        a channel
        """
        result = self.fetch_url(url)
        if not result:
            return
        response, data, meta = result
        title = self.parse(
            meta["final_url"],
            response,
            data,
            bad_cert=meta["bad_cert"]
        )
        # Add HTML link to re-mapped arXiv PDF urls
        if self.is_arXiv_mappable(url):
            title += ' | {}'.format(response.url)
        return title

    def fetch_url(self, url):
        """
        Fetch our given URL. Use retries, SSL handling, and malformed
        URL detection to get a robust fetch.
        """
        print "Fetching {}".format(url)
        s = requests.Session()
        s.mount('https://', MyAdapter())

        # if we have an arXiv PDF, just grab the HTML version if we can
        if self.is_arXiv_mappable(url):
            return self.fetch_url(self.arXiv_pdf2html_url(url))

        # keep track of the final url we used to complete the request so
        # that if we end up stripping trailing punctuation then we know
        # which URL we fetched. this is different from response.url, which
        # will show us the final redirected URL if redirect occurred
        # most of the time this will simply be the initial URL found in msg
        final_url = url

        # punctuation chars to attempt to remove from the end of
        # a url in the case of 404 or some other error code. we
        # have to do this because the supyboy.utils.urlRe regex
        # isn't perfect
        end_punct = "'\".?!"

        # information about our url's SSL status
        bad_cert = False
        verify_ssl = True

        # break out once we have a url of have exhausted retries
        retry = 0
        response = None
        while retry < MAX_RETRIES:
            print "Fetch try", retry
            retry += 1
            try:
                response = s.get(
                    url,
                    cookies=self.cj,
                    verify=verify_ssl,
                    headers={'User-agent': USERAGENT}
                )
            # TODO: make this a configurable functionality
            except requests.exceptions.SSLError:
                print "Bad cert!"
                bad_cert = True
                verify_ssl = False
                continue
            except Exception, e:
                print u"Requests get error: {}".format(e)
                continue

            # if we got an error code and we have a punctuation character at
            # the end of the url, attempt to strip it and try the url again
            if response.status_code in [404, 400, 504] and url[-1] in end_punct:
                url = url[:-1]
                final_url = url
                continue

            # success (presumably)
            break

        print "response", response

        # bummer ...
        if response is None:
            return

        data = response.content
        contenttype = response.headers.get('Content-Type')
        # Scrub potentially malformed HTML with lxml first
        if 'text/html' in contenttype:
            try:
                data = lxml.html.tostring(lxml.html.fromstring(data))
            except NameError:
                # lxml isn't installed, just try the html as is
                pass
            else:
                print "Scrubbed HTML data"

        # store metadata about the request, such as SSL validity, and other
        # things we did to make the request successful
        metadata = {
            "bad_cert": bad_cert,
            "final_url": final_url
        }

        return response, data, metadata

    def parse(self, url, response, data, bad_cert=False):
        """
        Take our retrieved page (and some metadata) and construct a title
        message from it based on status, content type, etc.
        """
        code = response.status_code
        contenttype = response.headers.get('content-type')

        # requests sets the response.url as the final url in the case
        # of a series of redirects/rewrites
        finalurl = response.url
        domain = urlparse.urlparse(url).hostname.lower()

        # some requests won't have this set. we should omit it in that case
        cl = response.headers.get('content-length', None)
        if not cl:
            cl = len(response.content) or None

        # a friendly size, i.e., 200KB, 1.3MB
        size = self.sizeof_fmt(cl)

        # these help the XML parser decode the page
        options = {}
        charset = contenttype.split('charset=')
        if len(charset) == 2:
            options['fromEncoding'] = charset[-1]

        statusinfo = []
        statusstring = ''

        # TODO: make this a configurable functionality
        if bad_cert:
            statusinfo.append('WARNING: BAD CERT')
        if code != 200:
            statusinfo.append(str(code))

        # redirect check
        is_redirect = lambda r: r.status_code in [301, 302]
        n_redirects = len(filter(is_redirect, response.history))
        if n_redirects > 0:
            redir_str = self.parse_redirect(response)
            if redir_str:
                statusinfo.append('R: {0}'.format(redir_str))

        # this is metadata about the request. includes things like bad cert
        # warning, non-200 response codes, etc
        if statusinfo:
            # make sure to put the space at the end here
            statusstring = '({0}) '.format(', '.join(statusinfo))

        # use youtube-API for this part
        if re.match("^https?://www.youtube.com/.*$", url) or \
                re.match("^https?://youtu.be/.*$"):
            video = pafy.new(url)
            return '[ {0} ({1}, {2}) ]'.format(
                statusstring, video.title, video.duration)

        # handle a normal web page
        elif 'text/html' in contenttype:
            soup = BeautifulSoup(
                data, convertEntities=BeautifulSoup.HTML_ENTITIES, **options
            )
            try:
                title = self.clean(soup.first('title').string)
            except AttributeError:
                domain = urlparse.urlparse(url).hostname
                if domain:
                    title = "No title: {}".format(domain[0])
                else:
                    title = "No title"

            return '[ {0}{1} ]'.format(statusstring, title.encode(ENCODING))

        # handle arXiv PDFs separately
        elif 'application/pdf' in contenttype and self.is_arXiv_mappable(url):
            html_url = self.arXiv_pdf2html_url(url)
            # recurse into our fetch_url parser since it will be
            # an HTML document this time around
            return self.get_title_url(html_url)

        # handle PDFs directly here
        elif 'application/pdf' in contenttype:
            # returns 'Title of PDF - 100 pages' or '' on error
            info = pdf2information(data)
            return '[ {0}{1} ({2}, {3}) {4} ]'.format(
                statusstring, info["title"], contenttype, info["pages"], size
            )

        # generic datatypes, list size and request status
        else:
            return '[ {0}({1}) {2} ]'.format( statusstring, contenttype, size)

    def parse_redirect(self, response):
        """
        Take a requests response object that we know contains a redirect
        in its response history and turn it into a short, readable string
        summarizing the nature of the redirection.
        """
        start = urlparse.urlparse(response.history[0].url)
        end = urlparse.urlparse(response.url)

        # first check to see if it's a domain/subdomain redirect
        if start.hostname != end.hostname:
            return end.hostname

        # then check to see if we did just a method change
        if start.scheme != end.scheme:
            return end.scheme.upper()

    def is_arXiv_mappable(self, url):
        """
        Determine whether an arxiv.org PDF url is mappable to its
        HTML counterpart. Use this in making the decision whether or
        not to try and extract PDF title from the document or to
        try and reconstruct the original HTML URL
        """
        return re.match(self.ARXIV_RE, url)

    def arXiv_pdf2html_url(self, pdf_url):
        """
        Take an arXiv PDF url and fetch the title from the corresponding
        HTML page, since arXiv has a deterministic mapping between the
        two. Example:
            PDF:  https://arxiv.org/pdf/1703.08251.pdf
            HTML: https://arxiv.org/abs/1703.08251
        """
        match = re.match(self.ARXIV_RE, pdf_url)
        document_id = match.groups()[0]
        return "https://arxiv.org/abs/{}".format(document_id)

    def sizeof_fmt(self, num):
        """ Convert a size in bytes into a human-friendly size.
        """
        if num is None:
            return ''

        num = int(num)
        for x in ['bytes','KB','MB','GB']:
            if num < 1024.0:
                return "%3.1f%s" % (num, x)
            num /= 1024.0
        return "%3.1f%s" % (num, 'TB')


Class = AcademicUrlTitles
# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
