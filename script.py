import gradio as gr
import re
import requests
import time
import xml.etree.ElementTree as ET
import yake

from modules.logging_colors import logger

params = {
    "arxiv_url": "http://export.arxiv.org/api/",
    "ncbi_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    "search_arxiv": False,
    "search_pubmed": True,
    "yake_limit": 0,
    "yake_score": 0.05
}

def add_context(articles, state):
    """
    Creates LLM context from a set of references.
    """
    for article in articles:
        if "id" in article and "title" in article:
            state["context"] += "\n\n"+article["id"]+"\ntitle: "+article["title"]
            if "abstract" in article:
                state["context"] += "\nabstract: "+article["abstract"]

def retrieve_arxiv(refs):
    """
    Retrieves titles and abstracts for a list of arXiv identifiers.
    """
    postdata = {
        "id_list": ",".join(set(refs))
    }
    xmlstring = requests.post(params["arxiv_url"]+"/query", data=postdata).text
    articles = []
    root = ET.fromstring(xmlstring)
    for node in root:
        if node.tag == "{http://www.w3.org/2005/Atom}entry":
            article = {}
            for node in node:
                if node.tag == "{http://www.w3.org/2005/Atom}id":
                    article["id"] = re.sub(r".*?([0-9][0-9][0-9][0-9]\.[0-9]+)(v[0-9]+)?", r"arXiv:\1", node.text)
                elif node.tag == "{http://www.w3.org/2005/Atom}title":
                    article["title"] = node.text
                elif node.tag == "{http://www.w3.org/2005/Atom}summary":
                    article["abstract"] = node.text
            articles.append(article)
    return articles

def retrieve_pubmed(refs):
    """
    Retrieves titles and abstracts for a list of PubMed identifiers.
    """
    postdata = {
        "db": "pubmed",
        "id": ",".join(set(refs))
    }
    xmlstring = requests.post(params["ncbi_url"]+"/efetch.fcgi", data=postdata).text
    articles = []
    root = ET.fromstring(xmlstring)
    for node in root:
        if node.tag == "PubmedArticle":
            article = {}
            for node in node:
                if node.tag == "MedlineCitation":
                    for node in node:
                        if node.tag == "PMID":
                            article["id"] = "PMID:"+node.text
                        elif node.tag == "Article":
                            for node in node:
                                if node.tag == "ArticleTitle" and node.text is not None:
                                    article["title"] = node.text
                                if node.tag == "Abstract":
                                    for node in node:
                                        if node.tag == "AbstractText" and node.text is not None:
                                            article["abstract"] = node.text
            articles.append(article)
    return articles

def search_arxiv(terms):
    """
    Search arXiv for a list of terms.
    """
    terms = ['"'+term+'"' for term in terms]
    if (len(terms) > 1):
        terms = list(set([i+" "+j for i,j in zip(terms, terms[1:])]))+list(set(terms))
    refs = set()
    for term in terms:
        postdata = {
            "max_results": 5,
            "search_query": term,
            "sortBy": "relevance"
        }
        xmlstring = requests.post(params["arxiv_url"]+"/query", data=postdata).text
        root = ET.fromstring(xmlstring)
        for node in root:
            if node.tag == "{http://www.w3.org/2005/Atom}entry":
                for node in node:
                    if node.tag == "{http://www.w3.org/2005/Atom}id":
                        refs.add(re.sub(r".*?([0-9][0-9][0-9][0-9]\.[0-9]+)(v[0-9]+)?", r"\1", node.text))
        if len(refs) >= 20:
            break
        time.sleep(1.0)
    return refs

def search_pubmed(terms):
    """
    Search Pubmed for a list of terms.
    """
    if (len(terms) > 1):
        terms = list(set([i+" AND "+j for i,j in zip(terms, terms[1:])]))+list(set(terms))
    refs = set()
    for term in terms:
        postdata = {
            "db": "pubmed",
            "retmax": 5,
            "sort": "relevance",
            "term": term
        }
        xmlstring = requests.post(params["ncbi_url"]+"/esearch.fcgi", data=postdata).text
        root = ET.fromstring(xmlstring)
        for node in root:
            if node.tag == "IdList":
                for node in node:
                    if node.tag == "Id":
                        refs.add(node.text)
        if len(refs) >= 20:
            break
        time.sleep(1.0)
    return refs

def ui():
    """
    Gets executed when the UI is drawn. Custom gradio elements and
    their corresponding event handlers should be defined here.
    """
    with gr.Accordion("Seshat", open=True):
        with gr.Row():
            search_arxiv = gr.Checkbox(label="Search arXiv", value=params["search_arxiv"])
            search_pubmed = gr.Checkbox(label="Search PubMed", value=params["search_pubmed"])
        with gr.Row():
            yake_limit = gr.Slider(0, 20, step=1, label="Maximum number of keywords", value=params["yake_limit"])
            yake_score = gr.Slider(0.00, 0.20, step=0.01, label="Maximum keyword score", value=params["yake_score"])
    search_arxiv.change(lambda x: params.update({"search_arxiv": x}), search_arxiv, None)
    search_pubmed.change(lambda x: params.update({"search_pubmed": x}), search_pubmed, None)
    yake_limit.change(lambda x: params.update({"yake_limit": x}), yake_limit, None)
    yake_score.change(lambda x: params.update({"yake_score": x}), yake_score, None)

def input_modifier(string, state, is_chat=False):
    """
    Modifies the user input before it is sent to the LLM.
    """
    articles = []
    arxiv_re = r"arxiv:? ?([0-9][0-9][0-9][0-9]\.[0-9]+)"
    arxiv_refs = re.findall(arxiv_re, string, re.IGNORECASE)
    articles += retrieve_arxiv(arxiv_refs)
    doi_re = r"doi: ?(10\.[0-9]+/[a-z0-9._;()/-]+)"
    doi_refs = re.findall(doi_re, string, re.IGNORECASE)
    pubmed_re = r"pmid:? ?0*([0-9]+)"
    pubmed_refs = re.findall(pubmed_re, string, re.IGNORECASE)
    articles += retrieve_pubmed(pubmed_refs)
    if articles:
        state["context"] += "\n\nAll following references should be cited."
        add_context(articles, state)
    articles = []
    search_re = r"\{(.+?)\}"
    search_terms = re.findall(search_re, string)
    if (params["yake_limit"] > 0):
        yake_keyword_extractor = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.9, top=params["yake_limit"], features=None)
        yake_keywords = [keyword[0] for keyword in yake_keyword_extractor.extract_keywords(string) if keyword[1]<=params["yake_score"]]
        if not yake_keywords:
            logger.warn("Seshat found no keywords with Yake.")
        search_terms += yake_keywords
    logger.info("Seshat search terms: "+", ".join(search_terms))
    if params["search_arxiv"]:
        arxiv_refs = search_arxiv(search_terms)
        if arxiv_refs:
            logger.info("Seshat arXiv search results:"+", ".join(arxiv_refs))
            articles += retrieve_arxiv(arxiv_refs)
    if params["search_pubmed"]:
        pubmed_refs = search_pubmed(search_terms)
        if pubmed_refs:
            logger.info("Seshat PubMed search results:"+", ".join(pubmed_refs))
            articles += retrieve_pubmed(pubmed_refs)
    if articles:
        state["context"] += "\n\nSome of the references below should be cited."
        add_context(articles, state)
    string = re.sub(search_re, r"\1", string)
    return string
