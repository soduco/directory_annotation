#!/usr/bin/env python3
import logging
import pandas
from tqdm import tqdm
from transform_directory_anotations import transform_directory_annotations
from create_directory_annotations import create_directory_annotations
from pathlib import Path
import os

# create logger
logger = logging.getLogger('soduco directory batch ')
logger.setLevel(logging.ERROR)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)

only_transform = False
force_iiif_creation = False
df = pandas.read_excel(r"directories_adress_lists_index_20230915.xlsx")
# filter the directories that have been processed
processed = df[df['selection_trait_soduco']>0]
ouvrages = sorted(processed['code_ouvrage'].unique())
for ouvrage in ouvrages:
  #logging.info(f"Ouvrage {ouvrage}")
  ouvrage_lines = processed[processed['code_ouvrage']==ouvrage]
  lists = sorted(ouvrage_lines['liste_type'].unique())
  for list in lists:
    #logging.info(f"\tListe {list}")
    list_lines = ouvrage_lines[ouvrage_lines['liste_type']==list]
    for list_index, (_,row) in enumerate(list_lines.iterrows()):
      #logging.info(f"\t\tSous-liste {list_index}")
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
      iiif_output_path = f"iiif/{collection_almanach}/{serie_almanach}/{code_ouvrage}/{liste_type}/part_{list_index}"
      if ark_index != -1:
        ark = url[ark_index:]
        logger.info(f"{code_fichier} / {code_ouvrage} ({annee}) = {ark}")
        input_path = f"annotations-20230911-ents/{code_fichier}"
        if os.path.exists(input_path):
          pdf_file_name = f"pdf/{code_fichier}.pdf"
          input_transform_manifest_path = f"annotations-20230911-manifest/{code_fichier}"
          if os.path.isdir(input_transform_manifest_path) or os.path.isfile(pdf_file_name):
            output_path = f"transform/{code_fichier}_annotations"
            if not os.path.exists(output_path):
              output_transform_manifest_path = f"annotations-20230911-transform-manifest/{code_fichier}"
              transform_directory_annotations(ark=ark, diff_vuepdf_vueark=int(diff_vuepdf_vueark), 
                                              directory_path=Path(input_path), 
                                              pdf_file_name=pdf_file_name, 
                                              output_path=Path(output_path), 
                                              input_transform_manifest_path=Path(input_transform_manifest_path),
                                              output_transform_manifest_path=Path(output_transform_manifest_path))
              if not only_transform:
                create_directory_annotations(label=liste_nom_original,directory_file_name=code_fichier,ark=ark,diff_vuepdf_vueark=int(diff_vuepdf_vueark),npage_pdf_d=npage_pdf_d,npage_pdf_f=npage_pdf_f,directory_path=Path(output_path),output=Path(iiif_output_path))
            else:
              logger.debug(f"\tIgnoring tranformation for {code_fichier}: alreading processed in {output_path}")
              if (not os.path.exists(iiif_output_path) or force_iiif_creation) and not only_transform:
                create_directory_annotations(label=liste_nom_original,directory_file_name=code_fichier,ark=ark,diff_vuepdf_vueark=int(diff_vuepdf_vueark),npage_pdf_d=npage_pdf_d,npage_pdf_f=npage_pdf_f,directory_path=Path(output_path),output=Path(iiif_output_path))
              else:
                logger.debug(f"\tIgnoring annotation creation for {code_fichier}: alreading processed in iiif/{ark}")
          else:
            logger.debug(f"\tIgnoring {code_fichier}: no file {pdf_file_name} or no path {input_transform_manifest_path}")
        else:
          logger.debug(f"\tIgnoring {code_fichier}: no path {input_path}")
    #    else:
    #        logger.info(f"NO ARK: {code_fichier} / {code_ouvrage} ({annee}) = {url}")

logger.info("All done!")