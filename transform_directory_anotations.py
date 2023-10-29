#!/usr/bin/env python3

import logging
import json
from iiif_prezi3 import config
import os
import numpy as np
import cv2
import math
from PIL import Image, TiffImagePlugin
from pikepdf import Pdf, PdfImage
import argparse
import pathlib
from tqdm import tqdm

import requests

logging.basicConfig(level=logging.INFO)
TiffImagePlugin.DEBUG = False

#TODO add scale parameter to skip detection (when it does not work as expected)?
#TODO use named arguments instead of positional?
def _get_parser():
  parser = argparse.ArgumentParser(
    prog="python transform_directory_annotations.py",
    description="Transform the annotations for a directory to be be in the IIIF coordinates"
  )
  parser.add_argument("ark",type=str,help="Ark of the directory")
  parser.add_argument("input_json",type=pathlib.Path,help="Path to the input json annotations")
  parser.add_argument("input_pdf",type=argparse.FileType('r'),help="Path to the input pfd")
  parser.add_argument("diff",type=int,help="Difference between pdf view and ark view")
  parser.add_argument("output",type=pathlib.Path,help="Path to the output annotations (json)")
  parser.add_argument("input_transform_manifest",type=pathlib.Path,help="Path to the input transform manifest (json)")
  parser.add_argument("output_transform_manifest",type=pathlib.Path,help="Path to the output transform manifest (json)")
  return parser

def get_shape(fname):
  img=Image.open(fname)
  return (img.size[0], img.size[1])

# Adapted from directory-annotator-back
class DocumentReadError(RuntimeError):
  pass
# Adapted from directory-annotator-back
class InvalidViewIndexError(RuntimeError):
  pass
# Adapted from directory-annotator-back
def get_pdf_shape_and_angle(pdfname,view):
  try:
    pdf_file = Pdf.open(pdfname)
    num_pages = len(pdf_file.pages)
    if not 1 <= view <= num_pages:
      raise InvalidViewIndexError()
    page = pdf_file.pages[view]
    for image in page.images:
      pdf_image = PdfImage(page.images[image]) # type: ignore
      img = pdf_image.as_pil_image()
      img = img.convert("L")
      img = np.array(img)
      count, angle = deskew_estimation(img, 5.0)
      if count == 0:
        logging.warning(f"No Segment detected for {pdfname} with view {view}")
      return pdf_image.height, pdf_image.width, angle
  except InvalidViewIndexError:
    raise
  except RuntimeError:
    raise DocumentReadError()

# Adapted from directory-annotator-back (inverse transform though)
def transform(xy, angle):
  x, y = xy
  c = -math.cos(angle)
  xx = x - y * c
  return xx, y

# Adapted from directory-annotator-back
def is_vertical(angle, tolerance):
  return np.abs(np.degrees(angle) - 90) < tolerance

# Adapted from directory-annotator-back
def deskew_estimation(img, tolerance):
  # using the parameters from directory-annotator-back
  lsd = cv2.createLineSegmentDetector(scale = 0.5,sigma_scale=0.6,quant=2.0,ang_th=22.5,log_eps=2.0,density_th=0.7,n_bins=1024)
  lines, _, _,_ = lsd.detect(img)
  _, width = img.shape[:2]
  kBorder = 0.1
  sum = 0
  count = 0
  for j in range(lines.shape[0]):
    x1, y1, x2, y2 = lines[j, 0, :]
    angle = np.arctan2(y2-y1, x2-x1)
    if angle<0:
      angle += np.pi# we want positive values
    if is_vertical(angle,tolerance):
      logging.debug(np.degrees(angle))
      # Dismiss segments on the left/right edges
      if not (min(x1, x2) < kBorder * width or max(x1, x2) > (1.0-kBorder) * width):
        sum += angle
        count += 1
  if count == 0:
    return count, np.pi / 2
  result = sum / count
  logging.debug(f"{count} segments detected with angle = {result} ({np.degrees(result)}°)")
  return count, result

def transform_directory_annotations(
    ark:str, 
    diff_vuepdf_vueark:int, 
    directory_path:pathlib.Path, 
    pdf_file_name:str, 
    output_path:pathlib.Path, 
    input_transform_manifest_path:pathlib.Path, 
    output_transform_manifest_path:pathlib.Path):
  os.makedirs(output_path, exist_ok=True)
  config.configs['helpers.auto_fields.AutoLang'].auto_lang = "fr"
  #FIXME This is ugly: it uses the initial manifest instead of single info files to make less requests
  original_manifest_url = f"https://gallica.bnf.fr/iiif/{ark}/manifest.json"
  url_response = requests.get(original_manifest_url)
  if url_response.ok:
    original_manifest_json = json.loads(url_response.text)
    shapes = {}
    for sequence in original_manifest_json["sequences"]:
      for canvas in sequence["canvases"]:
        shapes[canvas["@id"]] = (canvas["height"],canvas["width"])
    for file_path in tqdm(sorted(os.listdir(directory_path)),desc=f'Annotation tranform {directory_path}'):#[:5]:
      # check if current file_path is a json file
      if os.path.isfile(os.path.join(directory_path, file_path)) and file_path.endswith(".json"):
        view = int(file_path.split(".json")[0])
        #logging.debug(f"View {view}")
        h1, w1 = shapes[f"https://gallica.bnf.fr/iiif/{ark}/canvas/f{view+diff_vuepdf_vueark}"]
        if os.path.exists(input_transform_manifest_path):
          with open(os.path.join(input_transform_manifest_path, file_path.replace('.json','-manifest.json')), 'r') as file:
            data = json.load(file)
            angle = np.radians(data["angle"])
        else:
          res = get_pdf_shape_and_angle(pdf_file_name,view-1)#TODO check this view shift to make it more robust?
          if res:
            h2,w2,angle = res
          else:
            h2,w2,angle = h1,w1,np.pi / 2#if no shape from pdf
        # the images were resized so that the width of the output was 2048 so we resize boxes to fit the iiif width instead
        ratio = w1 / 2048.0
        if output_transform_manifest_path:
          os.makedirs(output_transform_manifest_path, exist_ok=True)
          with open(os.path.join(output_transform_manifest_path, file_path), 'w') as output_file:
            json.dump({"angle":np.degrees(angle),"ratio":ratio}, output_file, indent = 1)
        #logging.debug(f"{pdf_file_name} view {view} has {h2} and {w2} whereas iiif has {h1} and {w1} => ratio = {ratio}")
        with open(os.path.join(directory_path, file_path)) as file:
          data = json.load(file)
          for entry in data:
            if entry["box"]:
              in_box = entry["box"]
              p1, p2 = (in_box[0], in_box[1]), (in_box[0] + in_box[2], in_box[1] + in_box[3])
              pp1, pp2 = (p1[0] * ratio, p1[1] * ratio), (p2[0] * ratio, p2[1] * ratio)
              ppp1, ppp2 = transform(pp1, angle), transform(pp2, angle)
              entry["box"] = [ppp1[0], ppp1[1], ppp2[0] - ppp1[0], ppp2[1] - ppp1[1]]
          with open(os.path.join(output_path, file_path), 'w') as output_file:
            json.dump(data, output_file, indent = 1)
  else:
    logging.error(f"Directory {pdf_file_name} with {ark} not processed (GET failed for https://gallica.bnf.fr/iiif/{ark}/manifest.json)")

if __name__ == '__main__':
  parser = _get_parser()
  # Parse arguments
  args = parser.parse_args()
  vargs = vars(args)
  ark = vargs.pop("ark")
  diff_vuepdf_vueark = vargs.pop("diff")
  directory_path = vargs.pop("input_json")
  pdffile = vargs.pop("input_pdf")
  output_path = vargs.pop("output")
  input_transform_manifest = vargs.pop("input_transform_manifest")
  output_transform_manifest = vargs.pop("output_transform_manifest")
  transform_directory_annotations(ark, diff_vuepdf_vueark, directory_path, pdffile.name, output_path, input_transform_manifest, output_transform_manifest)