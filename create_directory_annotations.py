#!/usr/bin/env python3

import logging
import pandas
from pyproj import CRS, Transformer
import json
from os.path import exists
import sys
#from rdflib import Graph, BNode, Literal, RDF, URIRef#, GEO
from iiif_prezi3 import Manifest, config, Canvas, AnnotationPage, Annotation
import fiona
import geopandas
import os
import numpy as np
import cv2
import urllib.request
import math
from PIL import Image
from pikepdf import Pdf, PdfImage
import argparse
import pathlib
import requests

# FIXME the ark parameter only works for gallica/BnF: find parameters that work for other providers
def _get_parser():
  parser = argparse.ArgumentParser(
    prog="python create_directory_annotations.py",
    description="Create IIIF annotations for a directory"
  )
  parser.add_argument("directory",type=str,help="Directory name")
  parser.add_argument("ark",type=str,help="Ark of the directory")
  parser.add_argument("input_json",type=pathlib.Path,help="Path to the input json annotations")
  parser.add_argument("diff",type=int,help="Difference between pdf view and ark view")
  parser.add_argument("output",type=pathlib.Path,help="Path to the output IIIF annotations")
  return parser

def create_target(canvasid:str, box_types):
  switch={
    'PAGE': ("#0000ff", 0.5, 5),
    'ENTRY': ("#ff0000", 0.2, 4),
    'LINE': ("#00ff00", 1.0, 1),
    'PER': ("#7aecec", 1.0, 2),
    'ACT': ("#ff9561", 1.0, 2),
    'LOC': ("#bfeeb7", 1.0, 2),
    'CARDINAL': ("#feca74", 1.0, 2),
  }
  def path(box, color, opacity, width):
    return f"<path xmlns=\"http://www.w3.org/2000/svg\" d=\"M{box[0]},{box[1]}v{box[3]}h{box[2]}v-{box[3]}z\" fill=\"none\" stroke=\"{color}\" stroke-opacity=\"{opacity}\" stroke-width=\"{width}\"/>"
  paths=[]
  for box_type in box_types:
    box, type = box_type
    color, opacity, width = switch.get(type,("#ff0000", 1, 1))
    paths.append(path(box,color,opacity,width))
  return {
    "type": "SpecificResource",
    "source": canvasid,
    "selector":{
      "type": "SvgSelector",
      "value": f"<svg xmlns=\"http://www.w3.org/2000/svg\">{''.join(paths)}</svg>"
    }
  }
def getBoxFromChildren(entries):
  x,y=[],[]
  for entry in entries:
    box = entry["box"]
    x.append(box[0])
    x.append(box[0]+box[2])
    y.append(box[1])
    y.append(box[1]+box[3])
  return min(x),min(y),max(x)-min(x),max(y)-min(y)
def getBoxFromSpan(input_text:str,entries):
  for entry_index, entry in enumerate(entries):
    entry_text = entry["text"]
    if len(entry_text) > 0:
      index = entry_text.find(input_text)
      if index != -1:
        prop_start = index / len(entry_text)
        prop_end = (index + len(input_text)) / len(entry_text)
        box = entry["box"]
        return [(box[0]+prop_start*box[2],box[1],prop_end*box[2]-prop_start*box[2],box[3])],entry_index
  # if text not found as a whole, try by splitting in with '-'
  if '-' in input_text:
    boxes = []
    entry_index = -1
    for split_text in input_text.split('-'):
      res = getBoxFromSpan(split_text, entries)
      if res:
        boxes.extend(res[0])
        entry_index = res[1]
    if entry_index > 0:
      return boxes, entry_index
  return None
if __name__ == '__main__':
  parser = _get_parser()
  # Parse arguments
  args = parser.parse_args()
  vargs = vars(args)
  directory_name = vargs.pop("directory")
  ark = vargs.pop("ark")
  diff_vuepdf_vueark = vargs.pop("diff")
  directory_path = vargs.pop("input_json")
  output = vargs.pop("output")
  os.makedirs(f"iiif/{ark}", exist_ok=True)
  # prefix is useful for local testing
  prefix = "https://soduco.geohistoricaldata.org"#"http://localhost:8000"
  config.configs['helpers.auto_fields.AutoLang'].auto_lang = "fr"
  manifest = Manifest(
    #id=f"https://soduco.geohistoricaldata.org/{directory_name}/manifest.json",
    id=f"{prefix}/iiif/{ark}/manifest.json",
    label=f"{directory_name}",
    behavior=["individuals"],
    provider=[
      {
        "id": "https://gallica.bnf.fr",
        "type": "Agent",
        "label": { "en": [ "Gallica & The SoDUCo Project" ] },
        "homepage": {"id": "https://gallica.bnf.fr","type": "Text", "format": "text/html", "language": "en"},
        "logo": {"id": "https://gallica.bnf.fr/accueil/sites/all/modules/custom/gallica_tetierev3/images/Logo_BnF.png", "type": "Image", "format": "image/png","height": 50,"width": 110},
      },
      {
        "id": "https://soduco.geohistoricaldata.org",
        "type": "Agent",
        "label": { "en": [ "The SoDUCo Project" ] },
        "homepage": {"id": "https://soduco.geohistoricaldata.org","type": "Text", "format": "text/html", "language": "en"},
        "logo": {"id": "https://soduco.geohistoricaldata.org/public/images/soduco_logo.png", "type": "Image", "format": "image/png","height": 350,"width": 527},
      }
    ]) # type: ignore
  manifest.items = []
  original_manifest_url = f"https://gallica.bnf.fr/iiif/{ark}/manifest.json"
  url_response = requests.get(original_manifest_url)
  original_manifest_json = json.loads(url_response.text)
  shapes = {}
  for sequence in original_manifest_json["sequences"]:
    for canvas in sequence["canvases"]:
      shapes[canvas["@id"]] = (canvas["height"],canvas["width"])
  for file_path in sorted(os.listdir(directory_path)):
    # check if current file_path is a json file
    if os.path.isfile(os.path.join(directory_path, file_path)) and file_path.endswith(".json"):
      view = int(file_path.split(".json")[0])
      print(f"View {view}")
      height, width = shapes[f"https://gallica.bnf.fr/iiif/{ark}/canvas/f{view+diff_vuepdf_vueark}"]
      canvas = manifest.make_canvas(
        id=f"https://gallica.bnf.fr/iiif/{ark}/p{view+diff_vuepdf_vueark}",
        label=f"Page {view+diff_vuepdf_vueark}",
        height=height, width=width) # type: ignore
      anno_page = canvas.add_image(
        image_url=f"https://gallica.bnf.fr/iiif/{ark}/f{view+diff_vuepdf_vueark}/full/full/0/default.jpg",
        anno_page_id=f"https://gallica.bnf.fr/iiif/{ark}/p{view+diff_vuepdf_vueark}-page",
        anno_id=f"https://gallica.bnf.fr/iiif/{ark}/p{view+diff_vuepdf_vueark}-image",
        format="image/png",
        height=height,
        width=width)
      anno_page_temp = AnnotationPage(id=f"{prefix}/iiif/{ark}/p{view+diff_vuepdf_vueark}-annotation.json")
      anno_page_2 = AnnotationPage(id=f"{prefix}/iiif/{ark}/p{view+diff_vuepdf_vueark}-annotation.json")
      canvas.annotations = [anno_page_temp]
      with open(os.path.join(directory_path, file_path)) as file:
        data = json.load(file)
        def entry_entry(entry):
          return entry["type"] == "ENTRY"
        # filter entries
        for entry in filter(entry_entry,data):
          id = entry["id"]
          box = entry["box"]
          text = entry["text_ocr"]
          children = entry["children"]
          if entry["ents"]:
            ents = entry["ents"][0]
            def findChild(child_id:str, input_children:list[dict]):
              for c in input_children:
                if str(c["id"]) == child_id:
                  return c
              return None
            child_entries=[]
            for child in children:
              child_id = child.split("-")[-1]
              child_entry = findChild(child_id, data)
              if child_entry:
                child_entries.append(child_entry)
            if child_entries:
              new_box = getBoxFromChildren(child_entries)
            else:
              new_box = box
            box_types = [(new_box,entry["type"])]
            last_child = -1
            for ent in ents:
              ent_label = ent["label"]
              ent_text = ent["text"]
              #ent_span = ent["span"]
              res = getBoxFromSpan(ent_text,child_entries[last_child+1:])
              if res:
                ent_box, res_index = res
                for box in ent_box:
                  box_types.append((box,ent_label))
                last_child += res_index
            anno = Annotation(
              id=f"https://gallica.bnf.fr/iiif/{ark}/p{view+diff_vuepdf_vueark}-tag-{id}",
              motivation="tagging",
              body={"type": "TextualBody","language": "fr","format": "text/plain","value": text},
              target=create_target(canvas.id,box_types),
              anno_page_id=f"{prefix}/iiif/{ark}/p{view+diff_vuepdf_vueark}-annotation")
            anno_page_2.add_item(anno)
          else:
            print(f"no ents for entry {id}")
      json_canvas = json.loads(anno_page_2.json())
      with open(os.path.join(f"iiif/{ark}", f"p{view+diff_vuepdf_vueark}-annotation.json"), 'w') as output_file:
        json.dump(json_canvas, output_file, indent = 2)

  json_manifest = json.loads(manifest.json())
  # need to clean up the referenced version (iiif_prezi3 creates empty "items")
  for item in json_manifest["items"]:
    for annotation in item["annotations"]:
      del annotation["items"] 
  # adding logo (only one at a time for mirador)
  # FIXME choose logo depending on the provider
  json_manifest["logo"] = "https://www.bnf.fr/sites/default/files/logo.svg"#"https://soduco.geohistoricaldata.org/public/images/soduco_logo.png"
  with open(os.path.join(f"{output}/iiif/{ark}", "manifest.json"), 'w') as output_file:
    json.dump(json_manifest, output_file, indent = 2)
