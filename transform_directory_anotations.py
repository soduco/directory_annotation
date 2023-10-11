#!/usr/bin/env python3

import logging
import pandas
from pyproj import CRS, Transformer
import json
import sys
from iiif_prezi3 import Manifest, config
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

#TODO add scale parameter to skip detection (when it does not work as expected)?
#TODO use named arguments instead of positional?
def _get_parser():
  parser = argparse.ArgumentParser(
    prog="python transform_directory_annotations.py",
    description="Transform the annotations for a directory to be be in the IIIF coordinates"
  )
  parser.add_argument("directory",type=str,help="Directory name")
  parser.add_argument("ark",type=str,help="Ark of the directory")
  parser.add_argument("input_json",type=pathlib.Path,help="Path to the input json annotations")
  parser.add_argument("input_pdf",type=argparse.FileType('r'),help="Path to the input pfd")
  parser.add_argument("diff",type=int,help="Difference between pdf view and ark view")
  parser.add_argument("output",type=pathlib.Path,help="Path to the output annotations (json)")
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
      angle = deskew_estimation(img, 5.0)
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
  lsd = cv2.createLineSegmentDetector(0)
  lines, _, _,_ = lsd.detect(img)
  _, width = img.shape[:2]
  kBorder = 0.1
  sum = 0
  count = 0
  for j in range(lines.shape[0]):
    x1, y1, x2, y2 = lines[j, 0, :]
    angle = np.arctan2(y2-y1, x2-x1)
    if is_vertical(angle,tolerance):
      # Dismiss segments on the left/right edges
      if not (min(x1, x2) < kBorder * width or max(x1, x2) > (1.0-kBorder) * width):
        sum += angle
        count += 1
  if count == 0:
    print("No Segment detected")
    return np.pi / 2
  result = sum / count
  print(f"{count} segments detected with angle = {result} ({np.degrees(result)}°)")
  return result
# Adapted from directory-annotator-back
def detect_scale(width):
  s = math.log2(1024 / width)#FIXME: was math.log2(2048 / width) but scale was badly detected for didot so...
  rs = round(s)
  if abs(s - rs) > 0.2:
    return -1
  return int(rs)

if __name__ == '__main__':
  parser = _get_parser()
  # Parse arguments
  args = parser.parse_args()
  vargs = vars(args)
  directory_name = vargs.pop("directory")
  ark = vargs.pop("ark")
  diff_vuepdf_vueark = vargs.pop("diff")
  directory_path = vargs.pop("input_json")
  pdffile = vargs.pop("input_pdf")
  output_path = vargs.pop("output")
  os.makedirs(output_path, exist_ok=True)
  config.configs['helpers.auto_fields.AutoLang'].auto_lang = "fr"
  #FIXME This is ugly: it uses the initial manifest instead of single info files to make less requests
  original_manifest_url = f"https://gallica.bnf.fr/iiif/{ark}/manifest.json"
  url_response = requests.get(original_manifest_url)
  original_manifest_json = json.loads(url_response.text)
  shapes = {}
  for sequence in original_manifest_json["sequences"]:
    for canvas in sequence["canvases"]:
      shapes[canvas["@id"]] = (canvas["height"],canvas["width"])
  for file_path in sorted(os.listdir(directory_path)):#[:5]:
    # check if current file_path is a json file
    if os.path.isfile(os.path.join(directory_path, file_path)) and file_path.endswith(".json"):
      view = int(file_path.split(".json")[0])
      print(f"View {view}")
      # image_url = f"https://gallica.bnf.fr/iiif/{ark}/f{view+diff_vuepdf_vueark}/info.json"
      # url_response = requests.get(image_url)
      # info = json.loads(url_response.text)
      # h1,w1 = info["height"],info["width"]
      # print(info["height"],info["width"])
      h1, w1 = shapes[f"https://gallica.bnf.fr/iiif/{ark}/canvas/f{view+diff_vuepdf_vueark}"]
      res = get_pdf_shape_and_angle(pdffile.name,view-1)#TODO check this view shift to make it more robust?
      if res:
        h2,w2,angle = res
      else:
        h2,w2,angle = h1,w1,np.pi / 2#if no shape from pdf
      scale = detect_scale(w2)
      #TODO use a logger instead of print
      print(f"{pdffile.name} view {view} has {h2} and {w2} whereas iiif has {h1} and {w1}")
      print(f"scale = {scale} for {w2} => {math.log2(2048 / w2)}")
      subsampling_ratio = 1
      if (scale == 0):
        subsampling_ratio = 0.5
      yratio, xratio = h1 * subsampling_ratio / h2, w1 * subsampling_ratio / w2
      print(f"ratio = {xratio} x {yratio}")
      with open(os.path.join(directory_path, file_path)) as file:
        data = json.load(file)
        for entry in data:
          if entry["box"]:
            in_box = entry["box"]
            p1, p2 = (in_box[0], in_box[1]), (in_box[0] + in_box[2], in_box[1] + in_box[3])
            pp1, pp2 = p1[0] * xratio, p1[1] * yratio, p2[0] * xratio, p2[1] * yratio
            ppp1, ppp2 = transform(pp1, angle), transform(pp2, angle)
            entry["box"] = [ppp1[0], ppp1[1], ppp2[0] - ppp1[0], ppp2[1] - ppp1[1]]
        with open(os.path.join(output_path, file_path), 'w') as output_file:
          json.dump(data, output_file, indent=2)
