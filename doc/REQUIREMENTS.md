# File Upload Service Requirements

## Description
We have the following design requirements:
1. Upload process is an independent process that receives upload requests from other services
2. Upload all files that match a glob pattern.
3. The folder structure in the source shall be maintained in the destination
4. When file is finished uploading validate it was uploaded correctly

## Bonus requirements
1. The source folder shall be monitored for file changes (creation and modification)
   a. New files shall be uploaded
   b. When a file was modified – the new data should be uploaded (append to the existing uploaded file)

2. Once a big enough chunk of new data (can be hard coded or configurable) is written this data will be uploaded to the cloud to the same destination file
3. Check if this mean the process need to be always on and keep the cloud file open or it can be periodically activated
4. Design and implement a solution that is fail-safe, meaning, if the service fails, upon startup you can resume the existing uploads

## Input
The input request for the upload process shall include the following:
| Name               | Type           | Description                                                    |
|--------------------|----------------|----------------------------------------------------------------|
| upload_id          | String         | Identifier of the upload request                               |
| source_folder      | String         | Source folder to monitor                                       |
| destination_bucket | String         | The bucket name in the destination storage provider            |
| pattern            | String (Optional) | A glob pattern to filter the files to be uploaded           |

## Functional Requirements
The exercise includes two parts:
1. Design a high-level architecture for the system – you can provide a separate design diagram, or a more detailed one in the readme
2. Implement the system 
