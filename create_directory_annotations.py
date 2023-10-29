#!/usr/bin/env python3

import logging
import json
from iiif_prezi3 import Manifest, config, AnnotationPage, Annotation, ExternalItem, ServiceItem1
import os
import argparse
import pathlib
import requests
from tqdm import tqdm
logging.basicConfig(level=logging.INFO)

export_csv = False

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
    'ENTRY': ("#ff0000", 0.1, 4),
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
        prop_width = len(input_text) / len(entry_text)
        box = entry["box"]
        return [(box[0]+prop_start*box[2],box[1],prop_width*box[2],box[3])],entry_index
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
local = False
def create_directory_annotations(directory_name:str,ark:str,diff_vuepdf_vueark:int,directory_path:pathlib.Path,output:pathlib.Path):
  os.makedirs(f"iiif/{ark}", exist_ok=True)
  # prefix is useful for local testing
  if local:
    prefix = "http://localhost:8000"
  else:
    prefix = "https://directory.geohistoricaldata.org"
  config.configs['helpers.auto_fields.AutoLang'].auto_lang = "fr"
  manifest = Manifest(
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
  if url_response.ok:
    original_manifest_json = json.loads(url_response.text)
    shapes = {}
    for sequence in original_manifest_json["sequences"]:
      for canvas in sequence["canvases"]:
        shapes[canvas["@id"]] = (canvas["height"],canvas["width"])
    for file_path in tqdm(sorted(os.listdir(directory_path)),desc=f'Create IIIF for {directory_name} {ark}'):
      # check if current file_path is a json file
      if os.path.isfile(os.path.join(directory_path, file_path)) and file_path.endswith(".json"):
        pdf_view = int(file_path.split(".json")[0])
        ark_view = pdf_view+diff_vuepdf_vueark
        height, width = shapes[f"https://gallica.bnf.fr/iiif/{ark}/canvas/f{ark_view}"]
        try:
          canvas = manifest.make_canvas(
            id=f"https://gallica.bnf.fr/iiif/{ark}/p{ark_view}",
            label=f"Page {ark_view}",
            height=height, width=width) # type: ignore
        except:
          logging.error(f"Error for canvas https://gallica.bnf.fr/iiif/{ark}/canvas/f{ark_view} with {height}x{width}")
          os.removedirs(f"iiif/{ark}")
          return
        canvas.add_thumbnail(f"https://gallica.bnf.fr/{ark}/f{ark_view}.thumbnail")
        canvas.add_image(
          image_url=f"https://gallica.bnf.fr/iiif/{ark}/f{ark_view}/full/full/0/default.jpg",
          anno_page_id=f"https://gallica.bnf.fr/iiif/{ark}/p{ark_view}-page",
          anno_id=f"https://gallica.bnf.fr/iiif/{ark}/p{ark_view}-image",
          format="image/png",
          height=height,
          width=width,
          service=ServiceItem1(id=f"https://gallica.bnf.fr/iiif/{ark}/f{ark_view}",type="ImageService1",profile="level2"))
        anno_page_embedded = AnnotationPage(id=f"{prefix}/iiif/{ark}/p{ark_view}.json")
        anno_page_referenced = AnnotationPage(id=f"{prefix}/iiif/{ark}/p{ark_view}.json")
        canvas.annotations = [anno_page_embedded]
        transcript = []
        with open(os.path.join(directory_path, file_path)) as file:
          data = json.load(file)
          def entry_entry(entry):
            return entry["type"] == "ENTRY"
          # filter entries
          for entry in filter(entry_entry,data):
            id = entry["id"]
            box = entry["box"]
            text = entry["text_ocr"]
            ner_xml = entry["ner_xml"]
            children = entry["children"]
            if entry["ents"]:
              ents = entry["ents"]
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
              map = {}
              map["TITRE"] = []
              map["PER"] = []
              map["ACT"] = []
              map["LOC"] = []
              map["CARDINAL"] = []
              map["FT"] = []
              complete_ent_text = []
              for ent in ents:
                ent_label = ent["label"]
                ent_text = ent["text"]
                complete_ent_text.append(ent_text)
                map[ent_label].append(ent_text)
                #TODO for now, we don't use the span information
                #ent_span = ent["span"]
                res = getBoxFromSpan(ent_text,child_entries[last_child+1:])
                if res:
                  ent_box, res_index = res
                  for box in ent_box:
                    box_types.append((box,ent_label))
                  last_child += res_index
              anno = Annotation(
                id=f"{prefix}/iiif/{ark}/p{ark_view}-tag-{id}",
                motivation="tagging",
                body={"type": "TextualBody","language": "fr","format": "text/plain","value": text},
                target=create_target(canvas.id,box_types),
                anno_page_id=f"{prefix}/iiif/{ark}/p{ark_view}")
              anno_page_referenced.add_item(anno)
              def stringify(txt:str):
                if len(txt) > 0:
                  return "\""+txt+"\""
                else:
                  return txt
              transcript.append((directory_name,str(ark_view),
                                stringify(", ".join(complete_ent_text)),
                                  stringify(" & ".join(map["TITRE"])),
                                  stringify(" & ".join(map["PER"])),
                                  stringify(" & ".join(map["ACT"])),
                                  stringify(" & ".join(map["LOC"])),
                                  stringify(" & ".join(map["CARDINAL"])),
                                  stringify(" & ".join(map["FT"]))))
            else:
              #print(f"no ents for entry {id}")
              if text:
                transcript.append((directory_name,str(ark_view),text,"","","","","",""))
        json_canvas = json.loads(anno_page_referenced.json())
        with open(os.path.join(f"iiif/{ark}", f"p{ark_view}.json"), 'w') as output_file:
          json.dump(json_canvas, output_file, indent = 1)
        # Adding the rendering if there is any on the page
        if len(transcript) > 0:
          if export_csv:
            # create the file
            os.makedirs(f"txt/{ark}", exist_ok=True)
            with open(os.path.join(f"txt/{ark}", f"p{ark_view}.csv"), 'w') as output_file:
              output_file.write("filename,page,texte,title,person,activity,localisation,number,address_type\n")
              for tr in transcript:
                output_file.write(",".join(tr)+"\n")
            # add the rendering to the canvas
            rendering = ExternalItem(id=f"{prefix}/txt/{ark}/p{ark_view}.csv", type="Text", label="Transcript", format="text/csv")
          else:
            rendering = ExternalItem(id=f"https://api.geohistoricaldata.org/directories/export.csv?source=eq.{directory_name}&page=eq.{pdf_view:04d}", type="Text", label="Transcript", format="text/csv")
          canvas.rendering = [rendering]

    json_manifest = json.loads(manifest.json())
    # need to clean up the referenced version (iiif_prezi3 creates empty "items")
    for item in json_manifest["items"]:
      for annotation in item["annotations"]:
        del annotation["items"] 
    # adding logo (only one at a time for mirador)
    # FIXME choose logo depending on the provider
    json_manifest["logo"] = "https://www.bnf.fr/sites/default/files/logo.svg"#"https://soduco.geohistoricaldata.org/public/images/soduco_logo.png"
    with open(os.path.join(f"{output}/iiif/{ark}", "manifest.json"), 'w') as output_file:
      json.dump(json_manifest, output_file, indent = 1)
  else:
    logging.error(f"Directory {directory_name} with {ark} not processed (GET failed for https://gallica.bnf.fr/iiif/{ark}/manifest.json)")

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
  create_directory_annotations(directory_name,ark,diff_vuepdf_vueark,directory_path,output)