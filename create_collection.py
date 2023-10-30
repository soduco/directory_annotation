#!/usr/bin/env python3
import logging
import pandas
from tqdm import tqdm
from transform_directory_anotations import transform_directory_annotations
from create_directory_annotations import create_directory_annotations
from pathlib import Path
import os
import json
from iiif_prezi3 import Manifest, config, AnnotationPage, Annotation, ExternalItem, ServiceItem1, Collection, ResourceItem, Metadata, KeyValueString

# create logger
logger = logging.getLogger('create catalog')
logger.setLevel(logging.INFO)

df = pandas.read_excel(r"directories_adress_lists_index_20230915.xlsx")
df_complement = pandas.read_excel(r"directories_index_20231024.xlsx")
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
processed = df[df['selection_trait_soduco']>0]
processed_first = processed.groupby('Code_fichier').first().reset_index()
ouvrages = sorted(processed['code_ouvrage'].unique())
# build hierarchy
for ouvrage in ouvrages:
  logging.info(f"Ouvrage {ouvrage}")
  ouvrage_lines = processed[processed['code_ouvrage']==ouvrage]
  lists = sorted(ouvrage_lines['liste_type'].unique())
  for list in lists:
    logging.info(f"\tListe {list}")
    list_lines = ouvrage_lines[ouvrage_lines['liste_type']==list]
    for list_index, (_,row) in enumerate(list_lines.iterrows()):
      logging.info(f"\t\tSous-liste {list_index}")
      code_fichier = row['Code_fichier']
      code_ouvrage = row['code_ouvrage']
      collection_almanach = row['collection_almanach']
      serie_almanach = row['serie_almanach']
      liste_nom_original = row['liste_nom_original']
      annee = row['Liste_annee']
      liste_type = row['liste_type']
      url = row['lien_ouvrage_en_ligne']
      diff_vuepdf_vueark = row['diff_vuepdf_vueark']
      npage_pdf_d = row['npage_pdf_d']
      npage_pdf_f = row['npage_pdf_f']
      ark_index = url.find("ark")
      iiif_path = f"iiif/{collection_almanach}/{serie_almanach}/{code_ouvrage}/{liste_type}/part_{list_index}"
      if ark_index != -1:
        ark = url[ark_index:]
        logger.info(f"{code_fichier} / {code_ouvrage} ({annee}) = {ark}")
        ark_view = int(npage_pdf_d+diff_vuepdf_vueark)
        thumbnail = ResourceItem(id=f"https://gallica.bnf.fr/{ark}/f{ark_view}.thumbnail", type='Image', format="image/jpeg")
        list_manifest = Manifest(id=f"{prefix}/{iiif_path}/manifest.json",label=f"({code_ouvrage}-{liste_type}-p{list_index+1}) {liste_nom_original}",type="Manifest",thumbnail=thumbnail)
        if collection_almanach in collections:
          collection = collections[collection_almanach]
          if serie_almanach in collection:
            serie = collection[serie_almanach]
            if code_ouvrage in serie:
              directory = serie[code_ouvrage]
              directory.append(list_manifest)
            else:
              serie[code_ouvrage] = [list_manifest]
          else:
            collection[serie_almanach] = {code_ouvrage: [list_manifest]}
        else:
          collections[collection_almanach] = {serie_almanach:{code_ouvrage: [list_manifest]}}
# build manifest files for IIIF collections
for key_collection, value_collection in collections.items():
  collection_metadata = [
    KeyValueString(label={"en": ["collection_almanach"]},
                   value={"en": [key_collection]})
  ]
  print(key_collection)
  collection_title = df_complement[df_complement["collection"]==key_collection].iloc[0]["coll_titre"]
  collection_manifest = Collection(id=f"{prefix}/iiif/{key_collection}/manifest.json",label=f"({key_collection}) {collection_title}",metadata=collection_metadata)
  collection_manifest_ref = Collection(id=f"{prefix}/iiif/{key_collection}/manifest.json",label=f"({key_collection}) {collection_title}",metadata=collection_metadata)
  for key_serie, value_serie in value_collection.items():
    serie_metadata = [
      KeyValueString(label={"en": ["serie_almanach"]},
                     value={"en": [key_serie]})
    ]
    serie_title = df_complement[df_complement["serie"]==key_serie].iloc[0]["Série_titre"]
    serie_manifest = Collection(id=f"{prefix}/iiif/{key_collection}/{key_serie}/manifest.json",label=f"({key_serie}) {serie_title}",metadata=serie_metadata)
    serie_manifest_ref = Collection(id=f"{prefix}/iiif/{key_collection}/{key_serie}/manifest.json",label=f"({key_serie}) {serie_title}",metadata=serie_metadata)
    collection_manifest_ref.add_item_by_reference(serie_manifest)
    for key_directory, value_directory in value_serie.items():
      directory_metadata = [
        KeyValueString(label={"en": ["code_ouvrage"]},
                       value={"en": [key_directory]})
      ]
      print(key_directory)
      directory_title = df_complement[df_complement["code_ouvrage"]==key_directory].iloc[0]["titre ouvrage"]
      print(f"{directory_title} for {key_directory}")
      print(directory_metadata)
      directory_manifest = Collection(id=f"{prefix}/iiif/{key_collection}/{key_serie}/{key_directory}/manifest.json",label=f"({key_directory}) {directory_title}",metadata=directory_metadata)
      directory_manifest_ref = Collection(id=f"{prefix}/iiif/{key_collection}/{key_serie}/{key_directory}/manifest.json",label=f"({key_directory}) {directory_title}",metadata=directory_metadata)
      serie_manifest_ref.add_item_by_reference(directory_manifest)
      for value_list in value_directory:
        directory_manifest_ref.add_item(value_list)
      os.makedirs(f"iiif_collection/{key_collection}/{key_serie}/{key_directory}",exist_ok=True)
      with open(os.path.join(f"iiif_collection/{key_collection}/{key_serie}/{key_directory}", "manifest.json"), 'w') as output_file:
        json_directory_manifest_ref = json.loads(directory_manifest_ref.json())
        json.dump(json_directory_manifest_ref, output_file, indent = 1)
    os.makedirs(f"iiif_collection/{key_collection}/{key_serie}",exist_ok=True)
    with open(os.path.join(f"iiif_collection/{key_collection}/{key_serie}", "manifest.json"), 'w') as output_file:
      json_serie_manifest_ref = json.loads(serie_manifest_ref.json())
      json.dump(json_serie_manifest_ref, output_file, indent = 1)
  os.makedirs(f"iiif_collection/{key_collection}",exist_ok=True)
  with open(os.path.join(f"iiif_collection/{key_collection}", "manifest.json"), 'w') as output_file:
    json_collection_manifest_ref = json.loads(collection_manifest_ref.json())
    json.dump(json_collection_manifest_ref, output_file, indent = 1)
  manifest.items.append(collection_manifest)

json_manifest = json.loads(manifest.json())
#json_manifest["logo"] = "https://www.bnf.fr/sites/default/files/logo.svg"#"https://soduco.geohistoricaldata.org/public/images/soduco_logo.png"
with open(os.path.join(f"iiif_collection", "manifest.json"), 'w') as output_file:
  json.dump(json_manifest, output_file, indent = 1)

logger.info("All done!")