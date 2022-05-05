import os
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Union

from .constants import DEFAULT_REVISION, HUGGINGFACE_HUB_CACHE, REPO_TYPES
from .file_download import REGEX_COMMIT_HASH, hf_hub_download, repo_folder_name
from .hf_api import HfApi, HfFolder
from .utils import logging
from .utils._deprecation import _deprecate_positional_args


logger = logging.get_logger(__name__)


def _filter_repo_files(
    *repo_files: List[str],
    allow_regex: Optional[Union[List[str], str]] = None,
    ignore_regex: Optional[Union[List[str], str]] = None,
) -> List[str]:
    allow_regex = [allow_regex] if isinstance(allow_regex, str) else allow_regex
    ignore_regex = [ignore_regex] if isinstance(ignore_regex, str) else ignore_regex
    filtered_files = []
    for repo_file in repo_files:
        # if there's an allowlist, skip download if file does not match any regex
        if allow_regex is not None and not any(
            fnmatch(repo_file, r) for r in allow_regex
        ):
            continue

        # if there's a denylist, skip download if file does matches any regex
        if ignore_regex is not None and any(
            fnmatch(repo_file, r) for r in ignore_regex
        ):
            continue

        filtered_files.append(repo_file)
    return filtered_files


@_deprecate_positional_args
def snapshot_download(
    repo_id: str,
    *,
    revision: Optional[str] = None,
    repo_type: Optional[str] = None,
    cache_dir: Union[str, Path, None] = None,
    library_name: Optional[str] = None,
    library_version: Optional[str] = None,
    user_agent: Optional[Union[Dict, str]] = None,
    proxies: Optional[Dict] = None,
    etag_timeout: Optional[float] = 10,
    resume_download: Optional[bool] = False,
    use_auth_token: Optional[Union[bool, str]] = None,
    local_files_only: Optional[bool] = False,
    allow_regex: Optional[Union[List[str], str]] = None,
    ignore_regex: Optional[Union[List[str], str]] = None,
) -> str:
    """Download all files of a repo.

    Downloads a whole snapshot of a repo's files at the specified revision. This
    is useful when you want all files from a repo, because you don't know which
    ones you will need a priori. All files are nested inside a folder in order
    to keep their actual filename relative to that folder.

    An alternative would be to just clone a repo but this would require that the
    user always has git and git-lfs installed, and properly configured.

    Args:
        repo_id (`str`):
            A user or an organization name and a repo name separated by a `/`.
        revision (`str`, *optional*):
            An optional Git revision id which can be a branch name, a tag, or a
            commit hash.
        repo_type (`str`, *optional*):
            Set to `"dataset"` or `"space"` if uploading to a dataset or space,
            `None` or `"model"` if uploading to a model. Default is `None`.
        cache_dir (`str`, `Path`, *optional*):
            Path to the folder where cached files are stored.
        library_name (`str`, *optional*):
            The name of the library to which the object corresponds.
        library_version (`str`, *optional*):
            The version of the library.
        user_agent (`str`, `dict`, *optional*):
            The user-agent info in the form of a dictionary or a string.
        proxies (`dict`, *optional*):
            Dictionary mapping protocol to the URL of the proxy passed to
            `requests.request`.
        etag_timeout (`float`, *optional*, defaults to `10`):
            When fetching ETag, how many seconds to wait for the server to send
            data before giving up which is passed to `requests.request`.
        resume_download (`bool`, *optional*, defaults to `False):
            If `True`, resume a previously interrupted download.
        use_auth_token (`str`, `bool`, *optional*):
            A token to be used for the download.
                - If `True`, the token is read from the HuggingFace config
                  folder.
                - If a string, it's used as the authentication token.
        local_files_only (`bool`, *optional*, defaults to `False`):
            If `True`, avoid downloading the file and return the path to the
            local cached file if it exists.
        allow_regex (`list of str`, `str`, *optional*):
            If provided, only files matching this regex are downloaded.
        ignore_regex (`list of str`, `str`, *optional*):
            If provided, files matching this regex are not downloaded.

    Returns:
        Local folder path (string) of repo snapshot

    <Tip>

    Raises the following errors:

    - [`EnvironmentError`](https://docs.python.org/3/library/exceptions.html#EnvironmentError)
      if `use_auth_token=True` and the token cannot be found.
    - [`OSError`](https://docs.python.org/3/library/exceptions.html#OSError) if
      ETag cannot be determined.
    - [`ValueError`](https://docs.python.org/3/library/exceptions.html#ValueError)
      if some parameter value is invalid

    </Tip>
    """

    if cache_dir is None:
        cache_dir = HUGGINGFACE_HUB_CACHE
    if revision is None:
        revision = DEFAULT_REVISION
    if isinstance(cache_dir, Path):
        cache_dir = str(cache_dir)

    if isinstance(use_auth_token, str):
        token = use_auth_token
    elif use_auth_token:
        token = HfFolder.get_token()
        if token is None:
            raise EnvironmentError(
                "You specified use_auth_token=True, but a Hugging Face token was not"
                " found."
            )
    else:
        token = None

    if repo_type is None:
        repo_type = "model"
    if repo_type not in REPO_TYPES:
        raise ValueError("Invalid repo type")

    storage_folder = os.path.join(
        cache_dir, repo_folder_name(repo_id=repo_id, repo_type=repo_type)
    )

    # if we have no internet connection we will look for an
    # appropriate folder in the cache
    # If the specified revision is a commit hash, look inside "snapshots".
    # If the specified revision is a branch or tag, look inside "refs".
    if local_files_only:
        if REGEX_COMMIT_HASH.match(revision):
            snapshot_folder = os.path.join(storage_folder, "snapshots", revision)
            if os.path.exists(snapshot_folder):
                return snapshot_folder
        else:
            ref_path = os.path.join(storage_folder, "refs", revision)
            with open(ref_path) as f:
                commit_hash = f.read()
            snapshot_folder = os.path.join(storage_folder, "snapshots", commit_hash)
            if os.path.exists(snapshot_folder):
                return snapshot_folder

        raise ValueError(
            "Cannot find an appropriate cached folder for the specified revision on the"
            " local disk and outgoing traffic has been disabled. To enable repo"
            " look-ups and downloads online, set 'local_files_only' to False."
        )

    # if we have internet connection we retrieve the correct folder name from the huggingface api
    _api = HfApi()
    repo_info = _api.repo_info(
        repo_id=repo_id, repo_type=repo_type, revision=revision, token=token
    )
    filtered_repo_files = _filter_repo_files(
        repo_files=[f.rfilename for f in repo_info.siblings],
        allow_regex=allow_regex,
        ignore_regex=ignore_regex,
    )
    commit_hash = repo_info.sha
    snapshot_folder = os.path.join(storage_folder, "snapshots", commit_hash)

    # we pass the commit_hash to hf_hub_download
    # so no network call happens if we already
    # have the file locally.

    for repo_file in filtered_repo_files:
        _ = hf_hub_download(
            repo_id,
            filename=repo_file,
            repo_type=repo_type,
            revision=commit_hash,
            cache_dir=storage_folder,
            library_name=library_name,
            library_version=library_version,
            user_agent=user_agent,
            proxies=proxies,
            etag_timeout=etag_timeout,
            resume_download=resume_download,
            use_auth_token=use_auth_token,
        )

    return snapshot_folder
