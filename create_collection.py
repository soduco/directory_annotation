#!/usr/bin/env python3
import logging
import pandas
from tqdm import tqdm
from transform_directory_anotations import transform_directory_annotations
from create_directory_annotations import create_directory_annotations
from pathlib import Path
import os
import json
from iiif_prezi3 import Manifest, config, AnnotationPage, Annotation, ExternalItem, ServiceItem1, Collection, ResourceItem

# create logger
logger = logging.getLogger('create catalog')
logger.setLevel(logging.INFO)

df = pandas.read_excel(r"/home/JPerret/Documents/SODUCO/directories_adress_lists_index_20230915.xlsx")
# filter the directories that have been processed
os.makedirs(f"iiif_collection/", exist_ok=True)
# prefix is useful for local testing
local=False
if local:
  prefix = "http://localhost:8000"
else:
  prefix = "https://directory.geohistoricaldata.org"
config.configs['helpers.auto_fields.AutoLang'].auto_lang = "fr"
manifest = Collection(
id=f"{prefix}/iiif/manifest.json",
label=f"SoDUCo Directory Collection",
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
collections = {}
processed = df[df['selection_trait_soduco']==1]
processed_first = processed.groupby('Code_fichier').first().reset_index()
for index, row in processed_first.iterrows():#,desc='Batch processing':
  code_fichier = row['Code_fichier']
  code_ouvrage = row['code_ouvrage']
  annee = row['Liste_annee']
  url = row['lien_ouvrage_en_ligne']
  diff_vuepdf_vueark = row['diff_vuepdf_vueark']
  ark_index = url.find("ark")
  collection_almanach = row['collection_almanach']
  serie_almanach = row['serie_almanach']
  if ark_index != -1:
    ark = url[ark_index:]
    logger.info(f"{code_fichier} / {code_ouvrage} ({annee}) = {ark}")
    start_page = row['npage_pdf_d']
    ark_view = int(start_page+diff_vuepdf_vueark)
    thumbnail = ResourceItem(id=f"https://gallica.bnf.fr/{ark}/f{ark_view}.thumbnail", type='Image', format="image/jpeg")
    directory_manifest = Manifest(id=f"{prefix}/iiif/{ark}/manifest.json",label=f"{code_fichier}",type="Manifest",thumbnail=thumbnail)
    if collection_almanach in collections:
      collection = collections[collection_almanach]
      if serie_almanach in collection:
        serie = collection[serie_almanach]
        serie.append(directory_manifest)
      else:
        collection[serie_almanach] = [directory_manifest]
    else:
      collections[collection_almanach] = {serie_almanach:[directory_manifest]}
    #catalog.append({"manifestId": f"{prefix}/iiif/{ark}/manifest.json"})
for key, value in collections.items():
  collection_manifest = Collection(id=f"{prefix}/iiif/{key}/manifest.json",label=f"{key}")
  collection_manifest_ref = Collection(id=f"{prefix}/iiif/{key}/manifest.json",label=f"{key}")
  for key_serie, value_serie in value.items():
    serie_manifest = Collection(id=f"{prefix}/iiif/{key}/{key_serie}/manifest.json",label=f"{key_serie}")
    serie_manifest_ref = Collection(id=f"{prefix}/iiif/{key}/{key_serie}/manifest.json",label=f"{key_serie}")
    #collection_manifest.add_item(serie_manifest)
    collection_manifest_ref.add_item_by_reference(serie_manifest)
    for value_directory in value_serie:
      #serie_manifest.add_item(value_directory)
      serie_manifest_ref.add_item(value_directory)
    os.makedirs(f"iiif_collection/{key}/{key_serie}",exist_ok=True)
    with open(os.path.join(f"iiif_collection/{key}/{key_serie}", "manifest.json"), 'w') as output_file:
      json_serie_manifest_ref = json.loads(serie_manifest_ref.json())
      json.dump(json_serie_manifest_ref, output_file, indent = 1)
  os.makedirs(f"iiif_collection/{key}",exist_ok=True)
  with open(os.path.join(f"iiif_collection/{key}", "manifest.json"), 'w') as output_file:
    json_collection_manifest_ref = json.loads(collection_manifest_ref.json())
    json.dump(json_collection_manifest_ref, output_file, indent = 1)
  manifest.items.append(collection_manifest)

json_manifest = json.loads(manifest.json())
#json_manifest["logo"] = "https://www.bnf.fr/sites/default/files/logo.svg"#"https://soduco.geohistoricaldata.org/public/images/soduco_logo.png"
with open(os.path.join(f"iiif_collection", "manifest.json"), 'w') as output_file:
  json.dump(json_manifest, output_file, indent = 1)

logger.info("All done!")